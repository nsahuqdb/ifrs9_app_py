"""The assistant: its tools, its protocol, and how it behaves unconfigured.

No model is called anywhere here. The tools are the part that touches real
data and the part a wrong answer would come from, so they are what is tested;
the loop is exercised against a stub that plays the protocol back.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.assistant import execute_tool, load_config
from backend.assistant.agent import answer, extract_json
from backend.assistant.config import AssistantConfig
from backend.main import app

client = TestClient(app)

RUNS = [r["run_id"] for r in client.get("/api/runs").json()
        if r.get("has_report")]
RUN = RUNS[0] if RUNS else None
PAIR = (RUNS[1], RUNS[0]) if len(RUNS) > 1 else None
needs_run = pytest.mark.skipif(RUN is None, reason="set IFRS9_RUNS_DIR")
needs_pair = pytest.mark.skipif(PAIR is None, reason="two runs are needed")


class TestUnconfigured:
    def test_it_says_why_rather_than_failing_on_the_first_question(self):
        body = client.get("/api/assistant/status").json()
        if body["available"]:
            pytest.skip("this deployment has an endpoint configured")
        assert body["reason"]
        assert body["tools"], "it should still say what it could look at"

    def test_asking_anyway_is_a_service_error_not_a_crash(self):
        if client.get("/api/assistant/status").json()["available"]:
            pytest.skip("configured")
        r = client.post("/api/assistant/ask", json={"question": "hello"})
        assert r.status_code == 503
        assert "endpoint" in r.json()["detail"].lower()

    def test_an_empty_question_is_refused(self):
        r = client.post("/api/assistant/ask", json={"question": "   "})
        assert r.status_code == 400

    def test_the_key_is_never_returned(self, monkeypatch):
        """Only whether one is present. The status endpoint is unauthenticated
        as far as this app is concerned."""
        monkeypatch.setenv("IFRS9_LLM_API_KEY", "super-secret-value")
        body = client.get("/api/assistant/status").json()
        assert "super-secret-value" not in str(body)

    def test_the_key_comes_from_the_environment_not_the_config(self, monkeypatch):
        cfg = AssistantConfig(api_key_env="SOME_OTHER_VAR")
        monkeypatch.delenv("SOME_OTHER_VAR", raising=False)
        assert cfg.api_key is None
        monkeypatch.setenv("SOME_OTHER_VAR", "abc")
        assert cfg.api_key == "abc"


class TestTools:
    @needs_run
    def test_the_run_list_is_real(self):
        r = execute_tool("list_runs")
        assert r["ok"] and RUN in r["summary"]

    @needs_run
    def test_an_aggregation_reproduces_the_stage_split(self):
        """The assistant's numbers must be the app's numbers."""
        r = execute_tool("aggregate", {
            "run_id": RUN, "file": "FinalEclReport",
            "group_by": "Ifrs Stage", "measure": "Cla Amount Onbal",
            "fn": "sum"})
        assert r["ok"]
        total = sum(row["Cla Amount Onbal"] for row in r["chart"]["rows"])
        staging = client.get(f"/api/analytics/{RUN}/staging").json()
        expected = sum(s["ecl"] for s in staging["distribution"])
        assert total == pytest.approx(expected, rel=1e-6)

    @needs_run
    def test_a_missing_column_says_which_columns_exist(self):
        """The model has to be able to correct itself from the message."""
        r = execute_tool("aggregate", {"run_id": RUN, "file": "FinalEclReport",
                                       "group_by": "Nonsense", "fn": "count"})
        assert not r["ok"]
        assert "Columns:" in r["summary"]

    @needs_run
    def test_a_missing_file_names_the_files_there_are(self):
        r = execute_tool("describe_file", {"run_id": RUN, "file": "Nope"})
        assert not r["ok"] and "FinalEclReport.csv" in r["summary"]

    @needs_run
    def test_the_model_spec_reads_the_frozen_config(self):
        """Config is not in a run's outputs, so this must not need a
        aggregation over one."""
        r = execute_tool("model_spec", {"run_id": RUN})
        if not r["ok"]:
            assert "config_used" in r["summary"]
            return
        assert "anchor" in r["summary"].lower()
        assert "VAR_" in r["summary"]

    @needs_pair
    def test_comparing_two_runs_reports_the_change(self):
        a, b = PAIR
        r = execute_tool("compare_runs", {
            "run_id_a": a, "run_id_b": b, "file": "FinalEclReport",
            "group_by": "Portfolio Code", "measure": "Cla Amount Onbal",
            "fn": "sum"})
        assert r["ok"] and "diff" in r["summary"]

    def test_an_unknown_tool_is_a_result_not_an_exception(self):
        r = execute_tool("drop_database", {})
        assert not r["ok"] and "no tool called" in r["summary"]

    def test_bad_arguments_are_a_result_not_an_exception(self):
        r = execute_tool("list_runs", {"wat": 1})
        assert isinstance(r, dict) and "summary" in r

    def test_there_are_no_write_tools(self):
        """Read-only is a property of the catalogue, not a promise in a prompt."""
        from backend.assistant.tools import _TOOLS
        forbidden = ("write", "delete", "approve", "run", "trigger", "set")
        for name in _TOOLS:
            assert not any(name.startswith(f) for f in forbidden), name


class TestProtocol:
    def test_plain_json_is_understood(self):
        got = extract_json('{"action":"final","answer":"hi"}')
        assert got["action"] == "final"

    def test_a_fenced_block_is_understood(self):
        got = extract_json('here you go\n```json\n{"action":"final",'
                           '"answer":"hi"}\n```\nthanks')
        assert got["answer"] == "hi"

    def test_a_markdown_escaped_underscore_is_repaired(self):
        """Small models write \\_ inside JSON strings, which is not a legal
        escape and would otherwise make the whole object unparseable."""
        got = extract_json(r'{"action":"tool","tool":"model\_spec","args":{}}')
        assert got["tool"] == "model_spec"

    def test_prose_is_not_json_and_is_not_forced_to_be(self):
        assert extract_json("I don't know.") is None
        assert extract_json("") is None


class _Stub:
    """A model that plays the protocol back: one tool call, then an answer."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def __call__(self, messages, cfg):
        self.seen.append(messages)
        return self.replies.pop(0)


class TestTheLoop:
    @staticmethod
    def cfg():
        return AssistantConfig(enabled=True, endpoint="http://stub",
                               model="stub", max_tool_calls=2)

    @needs_run
    def test_a_tool_call_is_executed_and_fed_back(self, monkeypatch):
        import backend.assistant.agent as agent
        stub = _Stub(['{"action":"tool","tool":"list_runs","args":{}}',
                      '{"action":"final","answer":"there are runs","chart_ref":null}'])
        monkeypatch.setattr(agent, "chat", stub)
        r = agent.answer("what runs are there?", cfg=self.cfg())
        assert r["ok"] and r["text"] == "there are runs"
        assert [s["tool"] for s in r["steps"]] == ["list_runs"]
        # the observation must reach the model, or the loop is decorative
        assert any("OBSERVATION" in m["content"] for m in stub.seen[-1])

    @needs_run
    def test_the_tool_call_limit_forces_an_answer(self, monkeypatch):
        import backend.assistant.agent as agent
        stub = _Stub(['{"action":"tool","tool":"overview","args":{"run_id":"latest"}}',
                      '{"action":"tool","tool":"runs","args":{}}',
                      '{"action":"tool","tool":"validation","args":{}}',
                      '{"action":"final","answer":"done"}'])
        monkeypatch.setattr(agent, "chat", stub)
        r = agent.answer("go", cfg=self.cfg())
        assert r["ok"] and r["text"] == "done"
        assert len(r["steps"]) == 2, "it must stop at max_tool_calls"

    @needs_run
    def test_a_chart_is_referenced_not_retyped(self, monkeypatch):
        """The app plots the tool's own numbers, so a chart cannot disagree
        with the table above it."""
        import backend.assistant.agent as agent
        stub = _Stub([
            '{"action":"tool","tool":"aggregate","args":'
            f'{{"run_id":"{RUN}","file":"FinalEclReport",'
            '"group_by":"Ifrs Stage","measure":"Cla Amount Onbal","fn":"sum"}}}',
            '{"action":"final","answer":"see chart","chart_ref":"t1"}'])
        monkeypatch.setattr(agent, "chat", stub)
        r = agent.answer("stage split", cfg=self.cfg())
        assert r["chart"] and r["chart"]["rows"]

    def test_an_unreachable_model_is_reported_not_raised(self, monkeypatch):
        import backend.assistant.agent as agent
        from backend.assistant.client import AssistantError

        def boom(messages, cfg):
            raise AssistantError("the gateway is down")

        monkeypatch.setattr(agent, "chat", boom)
        r = agent.answer("hello", cfg=self.cfg())
        assert not r["ok"] and "gateway" in r["text"]

    def test_prose_from_the_model_is_passed_through(self, monkeypatch):
        import backend.assistant.agent as agent
        monkeypatch.setattr(agent, "chat", _Stub(["I am not sure."]))
        r = agent.answer("hello", cfg=self.cfg())
        assert r["ok"] and r["text"] == "I am not sure."



# ---------------------------------------------------------------------------
# The domain tools: the same numbers as the pages, in shapes the app can show.
# ---------------------------------------------------------------------------
from backend.assistant import semantic as SEM  # noqa: E402
from backend.assistant import knowledge as KN  # noqa: E402


class TestDomainTools:
    @needs_run
    def test_every_tool_answers_or_says_why(self):
        for name, fn in SEM.TOOLS.items():
            args = {"query": "loss given default"} if name == "search_docs" else \
                {"symbol": "compute_ecl"} if name == "read_code" else \
                {"query": RUN} if name == "customer" else \
                {"name": "model.yml"} if name == "config_file" else {}
            r = fn(focus=RUN, **args)
            assert isinstance(r, dict) and r.get("summary"), name

    @needs_run
    def test_the_stage_split_is_the_staging_pages(self):
        r = SEM.breakdown(focus=RUN, by="stage", measure="ecl")
        page = client.get(f"/api/analytics/{RUN}/staging").json()["distribution"]
        got = {row["stage"]: row["ecl"] for row in r["table"]["rows"]}
        for s in page:
            assert got[s["stage"]] == pytest.approx(s["ecl"], rel=1e-9)

    @needs_run
    def test_two_dimensions_give_a_pivot_and_a_stacked_chart(self):
        r = SEM.breakdown(focus=RUN, by=["portfolio", "stage"])
        assert r["ok"] and "Total" in r["table"]["columns"]
        assert r["chart"]["kind"] == "stacked"
        total = sum(row["Total"] for row in r["table"]["rows"])
        assert total == pytest.approx(client.get(f"/api/analytics/{RUN}/summary").json()["ecl"], rel=1e-9)

    @needs_run
    def test_filters_and_unknown_values_say_what_exists(self):
        r = SEM.breakdown(focus=RUN, by="rating", filters={"stage": 2})
        assert r["ok"] and "stage = 2" in r["summary"]
        bad = SEM.breakdown(focus=RUN, by="rating", filters={"portfolio": "Nowhere"})
        assert not bad["ok"] and "Values:" in bad["summary"]

    @needs_run
    def test_runs_are_found_the_way_people_name_them(self):
        assert SEM.resolve_run("latest", None)[0] == RUNS[0]
        assert SEM.resolve_run(None, RUN)[0] == RUN
        n = int(RUN.rsplit("_", 1)[-1])
        assert SEM.resolve_run(f"run {n}", None)[0] == RUN
        assert SEM.resolve_run("nonsense-run", None)[0] is None

    @needs_pair
    def test_the_movement_adds_up_and_matches_the_page(self):
        a, b = PAIR
        r = SEM.movement(run_a=a, run_b=b, focus=b)
        rows = r["table"]["rows"]
        opening = rows[0]["amount"]
        closing = rows[-1]["amount"]
        steps = sum(x["amount"] for x in rows[1:-1])
        assert opening + steps == pytest.approx(closing, abs=1.0)
        page = client.get("/api/analytics/bridge", params={"prev": a, "curr": b}).json()
        assert closing == pytest.approx(page["closing"], rel=1e-9)

    @needs_pair
    def test_which_portfolio_moved_most(self):
        a, b = PAIR
        r = SEM.movement(run_a=a, run_b=b, level="portfolio", focus=b)
        assert r["ok"] and "Largest change" in r["summary"]
        changes = [abs(x["change"]) for x in r["table"]["rows"]]
        assert changes == sorted(changes, reverse=True)

    @needs_run
    def test_the_mev_coefficients_come_from_the_frozen_config(self):
        r = SEM.model(focus=RUN)
        if r["ok"]:
            assert "coefficient" in " ".join(r["table"]["columns"]).lower()

    def test_no_tool_writes(self):
        verbs = ("write", "delete", "approve", "trigger", "set", "apply", "create", "edit", "start")
        for name in SEM.TOOLS:
            assert not any(name.startswith(v) for v in verbs), name


class TestKnowledge:
    def test_the_documents_and_the_code_are_indexed(self):
        kinds = {c.kind for c in KN.index().chunks}
        assert {"doc", "code"} <= kinds

    def test_a_methodology_question_finds_the_methodology(self):
        hits = KN.search("loss given default collateral haircut", "docs", 3)
        assert any("Loss given default" in h.section for h in hits)

    def test_a_how_to_finds_the_manual(self):
        hits = KN.search("approve an overlay", "docs", 3)
        assert any(h.source == "user_manual" for h in hits)

    def test_code_is_found_by_its_parts(self):
        assert KN.code_symbol("compute_ecl") is not None
        assert any(h.kind == "code" for h in KN.search("compute ecl", "code", 3))


class TestAnswers:
    @staticmethod
    def cfg():
        return AssistantConfig(enabled=True, endpoint="http://stub", model="stub", max_tool_calls=4)

    @needs_run
    def test_tables_and_charts_are_the_tools_own(self, monkeypatch):
        import backend.assistant.agent as agent
        stub = _Stub(['{"action":"tool","tool":"breakdown","args":{"by":["portfolio","stage"]}}',
                      '{"action":"final","answer":"see","show":["t1"],"chart":"t1","cite":[],'
                      '"followups":["why?"]}'])
        monkeypatch.setattr(agent, "chat", stub)
        r = agent.answer("stage split by portfolio", run_id=RUN, cfg=self.cfg())
        assert r["tables"] and r["tables"][0]["rows"]
        assert r["chart"]["kind"] == "stacked"
        assert r["followups"] == ["why?"]

    def test_a_clarifying_question_comes_back_with_options(self, monkeypatch):
        import backend.assistant.agent as agent
        monkeypatch.setattr(agent, "chat", _Stub(
            ['{"action":"ask","question":"Which run?","options":["run_00001","run_00002"]}']))
        r = agent.answer("compare them", cfg=self.cfg())
        assert r["ask"] == {"question": "Which run?", "options": ["run_00001", "run_00002"]}
        assert r["text"] == "Which run?"

    def test_citations_are_the_passages_it_read(self, monkeypatch):
        import backend.assistant.agent as agent
        hit = KN.search("loss given default", "docs", 1)[0]
        monkeypatch.setattr(agent, "chat", _Stub(
            ['{"action":"tool","tool":"search_docs","args":{"query":"loss given default"}}',
             '{"action":"final","answer":"LGD is ...","cite":["%s"]}' % hit.id]))
        r = agent.answer("how is LGD calculated?", cfg=self.cfg())
        assert [c["id"] for c in r["cites"]] == [hit.id]

    def test_a_repeated_lookup_is_not_run_twice(self, monkeypatch):
        import backend.assistant.agent as agent
        call = '{"action":"tool","tool":"search_docs","args":{"query":"staging"}}'
        monkeypatch.setattr(agent, "chat", _Stub([call, call, '{"action":"final","answer":"ok"}']))
        r = agent.answer("staging?", cfg=self.cfg())
        assert len(r["steps"]) == 1 and r["text"] == "ok"

    def test_a_reply_with_literal_newlines_is_still_read(self):
        assert extract_json('{"action":"final","answer":"line 1\nline 2"}')["answer"] == "line 1\nline 2"


class TestNoInventedFigures:
    """What happened on 23 Nov 2026: the lookup returned the real Stage 2
    customers, and the model typed its own table of invented ids, names and
    amounts. Nothing the lookups did not give may reach the user."""

    FAKE = ("Here are the top 5 customers in Stage 2 by ECL:\n\n"
            "| Customer | ECL (QAR) |\n|---|---|\n"
            "| 20111 · Ahmed Trading | 177,923,847 |\n"
            "| 20412 · Ahmed Steel | 123,456,789 |\n\n"
            "The largest is 20111 · Ahmed Trading with 177.9 mln.")

    @staticmethod
    def cfg():
        return AssistantConfig(enabled=True, endpoint="http://stub", model="stub", max_tool_calls=4)

    def _ask(self, monkeypatch, replies):
        import json as _json
        import backend.assistant.agent as agent
        stub = _Stub(replies)
        monkeypatch.setattr(agent, "chat", stub)
        return agent.answer("now stage 2 customer top 5", run_id=RUN, cfg=self.cfg()), stub

    @needs_run
    def test_invented_rows_never_reach_the_user(self, monkeypatch):
        import json as _json
        call = '{"action":"tool","tool":"top","args":{"by":"customer","n":5,"filters":{"stage":2}}}'
        bad = _json.dumps({"action": "final", "answer": self.FAKE, "show": ["t1"]})
        r, stub = self._ask(monkeypatch, [call, bad, bad])
        for s in ("Ahmed", "177,923,847", "123,456,789", "20111", "177.9"):
            assert s not in r["text"], s
        assert r["tables"] and r["tables"][0]["rows"], "the real table is still shown"
        assert r["check"]["removed"] and r["check"]["typed_table"]

    @needs_run
    def test_the_model_is_told_which_figures_failed_and_can_correct(self, monkeypatch):
        import json as _json
        call = '{"action":"tool","tool":"top","args":{"by":"customer","n":5,"filters":{"stage":2}}}'
        bad = _json.dumps({"action": "final", "answer": self.FAKE, "show": ["t1"]})
        good = _json.dumps({"action": "final", "answer": "The five largest Stage 2 customers are in the table.",
                            "show": ["t1"]})
        r, stub = self._ask(monkeypatch, [call, bad, good])
        assert r["text"] == "The five largest Stage 2 customers are in the table."
        assert r["check"]["removed"] == 0

    @needs_run
    def test_true_figures_and_names_pass(self, monkeypatch):
        import json as _json
        from backend.assistant.agent import execute
        t = execute("top", {"by": "customer", "n": 5, "filters": {"stage": 2}}, RUN)
        row = t["table"]["rows"][0]
        ecl = row["ecl"]
        cust = row["customer"]
        text = f"The largest is {cust} with ECL of {ecl:,.0f} ({ecl / 1e6:,.1f} mln)."
        call = '{"action":"tool","tool":"top","args":{"by":"customer","n":5,"filters":{"stage":2}}}'
        r, _ = self._ask(monkeypatch, [call, _json.dumps({"action": "final", "answer": text})])
        assert r["text"] == text and r["check"]["removed"] == 0

    def test_without_any_lookup_an_amount_is_not_stated(self, monkeypatch):
        r, _ = self._ask(monkeypatch, ['{"action":"final","answer":"Stage 2 ECL is 482,113,200."}',
                                       '{"action":"final","answer":"Stage 2 ECL is 482,113,200."}'])
        assert "482" not in r["text"]

    def test_an_option_naming_a_customer_no_lookup_gave_is_dropped(self, monkeypatch):
        import json as _json
        ask = _json.dumps({"action": "ask", "question": "Which one?",
                           "options": ["20111 · Ahmed Trading", "20412 · Ahmed Steel"]})
        r, _ = self._ask(monkeypatch, [ask, ask])
        assert not (r["ask"] or {}).get("options")


class TestGround:
    def test_dates_runs_versions_and_counts_are_not_figures(self):
        from backend.assistant.ground import Facts, unsupported
        f = Facts(["nothing"])
        txt = ("Run run_00023 of 2026-09-30 (30/9/2026, Sep 2026) on engine 0.53.0 has 3 portfolios, "
               "Stage 2 and QDB 4+; see [k12] and the top 5.")
        assert unsupported(txt, f) == []

    def test_rounding_and_units(self):
        from backend.assistant.ground import Facts, unsupported
        f = Facts(["ECL 2,944,304 coverage 20.57%"], [{"share": 0.4859}])
        assert unsupported("ECL 2,944,304, about 2.9 mln, 2.94 mln; coverage 20.6%; share 48.6%", f) == []
        assert unsupported("ECL 3.4 mln", f) == ["3.4 mln"]

    def test_a_difference_or_share_of_two_figures_is_allowed(self):
        from backend.assistant.ground import Facts, unsupported
        f = Facts(["previous 1,943,114,303 current 2,250,116,279"])
        assert unsupported("up 307,001,976 (15.8%)", f) == []

    def test_a_typed_table_is_cut(self):
        from backend.assistant.ground import strip_tables
        out, cut = strip_tables("Top five:\n| a | b |\n|---|---|\n| 1 | 2 |\nDone.")
        assert cut and out == "Top five:\nDone."


class TestLookupsComeFirst:
    """23 Nov 2026: "where is stage 2 list?" got "I do not have the list ...
    use the top tool on the Tools page" with no lookup made."""

    BAD = ('I do not have the list of Stage 2 customers. To obtain this list, you would need to use the '
           '"top" tool with the filter set to Stage 2. You can do this by navigating to the "Tools" page '
           'and selecting the "top" tool, then specifying "customer" as the "by" parameter.')

    @staticmethod
    def cfg():
        return AssistantConfig(enabled=True, endpoint="http://stub", model="stub", max_tool_calls=4)

    @needs_run
    def test_the_list_is_looked_up_and_shown_whatever_the_model_says(self, monkeypatch):
        import json as _json
        import backend.assistant.agent as agent
        bad = _json.dumps({"action": "final", "answer": self.BAD})
        monkeypatch.setattr(agent, "chat", _Stub([bad, bad, bad]))
        hist = [{"role": "user", "content": "now stage 2 custometr top 5"},
                {"role": "assistant", "content": "..."}]
        r = agent.answer("where is stage 2 list?", history=hist, run_id=RUN, cfg=self.cfg())
        assert r["steps"] and r["steps"][0]["tool"] == "top"
        assert r["steps"][0]["args"]["filters"] == {"stage": 2}
        assert r["tables"] and r["tables"][0]["rows"]
        assert all(row["stage"] == "Stage 2" for row in r["tables"][0]["rows"])
        assert "tool" not in r["text"].lower() and "parameter" not in r["text"]

    @needs_run
    def test_a_good_model_answer_on_the_lookup_passes(self, monkeypatch):
        import json as _json
        import backend.assistant.agent as agent
        ok = _json.dumps({"action": "final", "answer": "The Stage 2 customers are listed below.",
                          "show": ["t1"]})
        stub = _Stub([ok])
        monkeypatch.setattr(agent, "chat", stub)
        r = agent.answer("list the stage 2 customers", run_id=RUN, cfg=self.cfg())
        assert r["text"] == "The Stage 2 customers are listed below."
        assert "OBSERVATION t1 (top)" in str(stub.seen[0])


class TestRouter:
    P = ["Business Finance", "Al Dhameen", "Tasdeer", "Off BS"]

    @pytest.mark.parametrize("q,tool,args", [
        ("where is stage 2 list?", "top", {"filters": {"stage": 2}}),
        ("now stage 2 custometr top 5", "top", {"n": 5, "filters": {"stage": 2}}),
        ("Top 10 customers by ECL", "top", {"n": 10, "by": "customer"}),
        ("top 20 Off BS contracts by exposure", "top",
         {"by": "contract", "measure": "exposure", "filters": {"portfolio": "Off BS"}}),
        ("show the stage split by portfolio", "breakdown", {"by": ["portfolio", "stage"]}),
        ("which portfolio moved most between the two runs?", "movement", {"level": "portfolio"}),
        ("Why did the ECL change since the previous run?", "movement", {"level": "book"}),
        ("what are the MEV coefficients?", "model", {}),
        ("which validation checks failed?", "validation", {"only_failures": True}),
        ("Plot the PD curves for QDB 3, QDB 5 and QDB 7", "pd_curve", {"ratings": ["QDB 3", "QDB 5", "QDB 7"]}),
        ("How is LGD calculated?", "search_docs", {}),
        ("what is the total provision?", "overview", {}),
        ("how much is stage 3 ECL in Tasdeer", "breakdown", {"filters": {"stage": 3, "portfolio": "Tasdeer"}}),
        ("how many customers in stage 3", "breakdown", {"measure": "customers"}),
    ])
    def test_the_usual_questions(self, q, tool, args):
        from backend.assistant.router import plan
        got = plan(q, None, self.P)
        assert got and got[0][0] == tool
        for k, v in args.items():
            assert got[0][1].get(k) == v, (q, got)

    def test_a_follow_up_borrows_the_previous_question(self):
        from backend.assistant.router import plan
        h = [{"role": "user", "content": "top 5 customers in stage 2"}]
        assert plan("and stage 3?", h, self.P) == [("top", {"by": "customer", "measure": "ecl", "n": 5,
                                                            "filters": {"stage": 3}})]

    def test_small_talk_is_left_to_the_model(self):
        from backend.assistant.router import plan
        assert plan("hello", None, self.P) == []


class TestAlternation:
    """23 Nov 2026: the endpoint refused the conversation (HTTP 400, "roles
    must alternate") once the first lookup was added before the model's turn."""

    def test_roles_alternate_after_system_whatever_the_loop_built(self):
        from backend.assistant.client import alternate
        msgs = [{"role": "system", "content": "S"},
                {"role": "assistant", "content": "earlier answer"},
                {"role": "user", "content": "q1"}, {"role": "user", "content": "q2"},
                {"role": "assistant", "content": "{tool}"},
                {"role": "user", "content": "OBSERVATION t1"}, {"role": "user", "content": "answer now"},
                {"role": "assistant", "content": "a"}, {"role": "assistant", "content": "b"}]
        out = alternate(msgs)
        assert out[0] == {"role": "system", "content": "S"}
        roles = [m["role"] for m in out[1:]]
        assert roles[0] == "user" and roles[-1] == "user"
        assert all(a != b for a, b in zip(roles, roles[1:]))
        joined = " ".join(m["content"] for m in out)
        for t in ("earlier answer", "q1", "q2", "OBSERVATION t1", "answer now", "a", "b"):
            assert t in joined

    @needs_run
    def test_every_request_the_loop_sends_alternates(self, monkeypatch):
        import json as _json
        import backend.assistant.agent as agent
        import backend.assistant.client as client
        sent = []

        class R:
            status_code = 200
            text = ""

            def __init__(self, c):
                self.c = c

            def json(self):
                return {"choices": [{"message": {"content": self.c}}]}

        replies = [_json.dumps({"action": "final", "answer": "Listed below.", "show": ["t1"]})]
        monkeypatch.setattr(client.requests, "post",
                            lambda url, json, **k: (sent.append(json["messages"]), R(replies.pop(0)))[1])
        monkeypatch.setattr(agent, "chat", client.chat)
        cfg = AssistantConfig(enabled=True, endpoint="http://stub", model="stub", max_tool_calls=4)
        hist = [{"role": "user", "content": "now stage 2 customer top 5"},
                {"role": "assistant", "content": "..."}]
        r = agent.answer("where is stage 2 list?", history=hist, run_id=RUN, cfg=cfg)
        assert r["tables"]
        for msgs in sent:
            roles = [m["role"] for m in msgs if m["role"] != "system"]
            assert roles[0] == "user" and roles[-1] == "user"
            assert all(a != b for a, b in zip(roles, roles[1:])), roles
