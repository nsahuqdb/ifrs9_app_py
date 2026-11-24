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
        d = r.json()["detail"].lower()
        assert "endpoint" in d or "api key" in d     # what is missing, in words

    def test_an_empty_question_is_refused(self):
        r = client.post("/api/assistant/ask", json={"question": "   "})
        assert r.status_code == 400

    def test_the_key_is_never_returned(self, monkeypatch):
        """Only whether one is present. The status endpoint is unauthenticated
        as far as this app is concerned."""
        monkeypatch.setenv("IFRS9_LLM_API_KEY", "super-secret-value")
        monkeypatch.setenv("QDB_GEMMA4_API_KEY", "sk-vllm-secret-value")
        body = client.get("/api/assistant/status").json()
        assert "super-secret-value" not in str(body) and "sk-vllm-secret-value" not in str(body)

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
        ("How is LGD calculated?", "explain", {}),
        ("How pit pd is calculated", "explain", {}),
        ("which customers moved from stage 2 to stage 3 in 2 runs", "stage_moves", {"from_stage": 2, "to_stage": 3}),
        ("which customers moved from stage 2 to stage 3 between run 22 and run 23", "stage_moves",
         {"run_a": "run_00022", "run_b": "run_00023"}),
        ("why is 20002 in stage 2", "stage_reason", {"query": "20002"}),
        ("why is Al Waha Trading in stage 2", "stage_reason", {"query": "Al Waha Trading"}),
        ("why are customers in stage 2", "staging", {}),
        ("what is the difference between run 22 and run 23", "compare", {"run_a": "run_00022"}),
        ("which customers cured", "stage_moves", {"direction": "better"}),
        ("rating migration", "migration", {"kind": "rating"}),
        ("where is the function that computes lgd", "search_docs", {"scope": "code"}),
        ("what are the scenario weights", "scenarios", {}),
        ("how are scenario weights set", "explain", {}),
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


class TestExplain:
    """24 Nov 2026: "How pit pd is calculated" got one line on the external
    PD and three code references. A methodology answer comes from the
    documents, whole, covers every version, and links to the section."""

    def test_pit_pd_brings_the_internal_and_the_external_model_and_the_factor(self):
        from backend.assistant.knowledge import explain
        heads = [c.heading for c in explain("How pit pd is calculated")]
        assert heads[:3] == ["7.3 Scaling factor", "7.4 Point-in-time PD and reversion to TTC",
                             "7.7 The external model (investments)"]

    @pytest.mark.parametrize("q,want", [
        ("how is lgd calculated", "9. Loss given default"),
        ("how is stage 2 decided", "6.1 The rule"),
        ("how is stage 3 ecl calculated", "10.3 Stage 3"),
        ("what is the exposure cap", "10.2 The exposure cap"),
        ("how is EAD calculated for off balance", "8.3 Off-balance products"),
        ("how are scenario weights set", "7.6 Scenario weights (internal scale)"),
        ("how do I approve an overlay", "9.5 Mark tested, approve, copy"),
        ("what is contagion", "6.1 The rule"),
    ])
    def test_the_section_that_answers_comes_back(self, q, want):
        from backend.assistant.knowledge import explain
        assert want in [c.heading for c in explain(q)]

    def test_only_the_help_documents_never_the_engine_notes(self):
        from backend.assistant.knowledge import HELP_PAGE_FILES, explain
        for q in ("how is lgd calculated", "what is the scaling factor", "how is the ecl discounted"):
            assert all(c.source in HELP_PAGE_FILES for c in explain(q))

    def test_each_section_links_to_its_help_page(self):
        from backend.assistant.semantic import explain
        r = explain("How pit pd is calculated")
        assert r["ok"] and len(r["docs"]) == 3
        for d in r["docs"]:
            assert d["link"]["page"] == "frontend/views/help_ecl.py"
            assert d["link"]["ch"] == "7. Probability of default" and d["link"]["sec"] == d["heading"]
            assert "$$" in d["text"]

    def test_the_answer_cites_documents_not_code(self, monkeypatch):
        import json as _json
        import backend.assistant.agent as agent
        ok = _json.dumps({"action": "final", "answer": "Two models, below.", "cite": ["k1"]})
        monkeypatch.setattr(agent, "chat", _Stub([ok]))
        cfg = AssistantConfig(enabled=True, endpoint="http://stub", model="stub", max_tool_calls=4)
        r = agent.answer("How pit pd is calculated", cfg=cfg)
        assert r["steps"][0]["tool"] == "explain"
        assert r["docs"] and all(c.get("kind") == "doc" for c in r["cites"])
        assert all(c.get("link") for c in r["cites"])

    def test_formulas_and_risk_parameter_are_not_tool_talk(self):
        from backend.assistant.ground import tool_talk
        assert tool_talk("It uses a risk parameter (R) and $$R = 0.24 - 0.12$$.") == []
        assert tool_talk('specify "customer" as the "by" parameter') != []


class TestStageMoves:
    @needs_run
    def test_who_moved_from_2_to_3_and_why(self):
        from backend.assistant.agent import execute
        r = execute("stage_moves", {"from_stage": 2, "to_stage": 3}, RUN)
        assert r["ok"]
        rows = r["table"]["rows"]
        assert rows and all(x["from"] == 2 and x["to"] == 3 for x in rows)
        assert all(x["reason now"] and x["what changed"] for x in rows)
        # the ECL change is the difference of the two runs' ECL
        for x in rows:
            assert abs(x["ecl_change"] - (x["ecl"] - x["ecl_prev"])) < 1e-6

    @needs_run
    def test_why_one_customer_is_in_its_stage(self):
        from backend.assistant.agent import execute
        from backend.assistant.semantic import customer_stages
        cv = customer_stages(RUN)
        s2 = cv[cv["stage"] == 2].iloc[0]
        r = execute("stage_reason", {"query": str(s2["customer"])}, RUN)
        assert r["ok"] and f"Stage 2" in r["summary"] and s2["reason"] in r["summary"]

    @needs_run
    def test_every_stage_2_and_3_customer_has_a_reason(self):
        from backend.assistant.semantic import customer_stages
        cv = customer_stages(RUN)
        bad = cv[(cv["stage"] >= 2) & cv["reason"].str.startswith("No ")]
        assert len(bad) == 0, bad[["customer", "stage", "reason"]].head().to_dict("records")


class TestPresentation:
    """The app picks table, chart or both unless the user says."""

    @staticmethod
    def _show(question, tool, chart=True, rows=5):
        from backend.assistant.agent import present
        res = {"tool": tool, "table": {"rows": [{}] * rows},
               "chart": {"rows": [{}] * rows} if chart else None}
        return present(question, res)

    def test_defaults(self):
        assert self._show("ecl by stage", "breakdown") == ("both", True)
        assert self._show("why did the ecl change", "movement") == ("both", True)
        assert self._show("top 10 customers", "top") == ("table", False)
        assert self._show("pd curves for QDB 3", "pd_curve") == ("chart", True)
        assert self._show("ecl by customer", "breakdown", rows=40) == ("table", False)

    def test_what_the_user_asks_for_wins(self):
        assert self._show("top 10 customers as a chart", "top") == ("chart", True)
        assert self._show("ecl by stage as a table", "breakdown") == ("table", False)
        assert self._show("ecl by stage, table and chart", "breakdown") == ("both", True)


class TestRegulatory:
    """24 Nov 2026: the assistant should know the regulations and compare
    QDB's settings with them (e.g. our haircuts vs QCB / Basel)."""

    @staticmethod
    def _live():
        from pathlib import Path
        import ifrs9qdb
        root = Path(ifrs9qdb.__file__).resolve().parent
        return root / "config", root / "static"

    def test_qdb_haircuts_are_read_from_the_config_and_explained(self):
        from backend.assistant import regulatory as R
        q = R.qdb_settings(*self._live())
        rows = {r["item"]: r for r in R.benchmark_rows(q, "collateral")}
        cash = rows["Cash collateral / collateral account"]
        assert cash["QDB"] == "100% haircut (nothing counted)"
        assert cash["Basel"].startswith("0%") and "CRE22.49" in cash["Basel ref"]
        assert rows["Residential property"]["QDB"] == "50% haircut (50% of value counted)"
        assert rows["Commercial property"]["QDB"] == "75% haircut (25% of value counted)"
        assert rows["Bank guarantee"]["QDB"] == "0% haircut (counted in full)"

    def test_a_changed_haircut_shows_in_the_comparison(self, tmp_path):
        import shutil
        from backend.assistant import regulatory as R
        cfg, static = self._live()
        st = tmp_path / "static"
        shutil.copytree(static, st)
        p = st / "collateral_types.csv"
        p.write_text(p.read_text().replace("22,1,Cash Collateral,1.00", "22,1,Cash Collateral,0.10"))
        rows = {r["item"]: r for r in R.benchmark_rows(R.qdb_settings(cfg, st), "collateral")}
        assert rows["Cash collateral / collateral account"]["QDB"].startswith("10% haircut (90% of value")

    def test_lgd_and_staging_benchmarks_carry_their_paragraphs(self):
        from backend.assistant import regulatory as R
        q = R.qdb_settings(*self._live())
        lgd = {r["item"]: r for r in R.benchmark_rows(q, "lgd")}
        assert lgd["LGD on the unsecured part"]["QDB"] == "45%"
        assert "40%" in lgd["LGD on the unsecured part"]["Basel"] and "CRE32.6" in lgd["LGD on the unsecured part"]["Basel ref"]
        assert lgd["Lowest LGD possible"]["QDB"].startswith("22.5%")
        stg = {r["item"]: r for r in R.benchmark_rows(q, "staging")}
        assert stg["Stage 2 backstop (days past due)"]["QDB"] == "worst DPD above 60 days"
        assert "5.5.11" in stg["Stage 2 backstop (days past due)"]["IFRS 9 ref"]
        assert "B5.5.37" in stg["Default (Stage 3)"]["IFRS 9 ref"]

    def test_the_reference_document_agrees_with_the_benchmarks(self):
        from pathlib import Path
        doc = (Path(__file__).resolve().parents[1] / "docs" / "regulatory_reference.md").read_text()
        for s in ("| Cash in the same currency | 0% |", "CRE22.52", "| Senior unsecured, non-financial corporates | 40% | CRE32.6 |",
                  "| Short-term self-liquidating trade letters of credit | 20% | CRE20.99 |", "B5.5.37", "5.5.11",
                  "| PD, corporate and bank exposures (not sovereigns) | 0.05% | CRE32.4 |"):
            assert s in doc, s

    def test_folder_texts_are_read_cited_by_page_and_cached(self, tmp_path, monkeypatch):
        from backend.assistant import regulatory as R
        (tmp_path / "QCB").mkdir()
        (tmp_path / "QCB" / "instructions.md").write_text(
            "Section 3. Collateral. Residential real estate is taken at a haircut of thirty percent.\n" * 3)
        (tmp_path / "broken.pdf").write_bytes(b"not a pdf")
        monkeypatch.setattr(R, "REG_DIR", tmp_path)
        monkeypatch.setattr(R, "_CACHE", tmp_path / ".index")
        chunks, listing = R.folder()
        docs = {d["document"]: d for d in listing}
        assert docs["instructions.md"]["problem"] == "" and docs["broken.pdf"]["problem"]
        assert chunks and chunks[0].where == "docs/regulatory/QCB/instructions.md"
        assert (tmp_path / ".index").is_dir()
        from backend.assistant.semantic import regulation
        r = regulation("residential real estate haircut")
        assert r["ok"] and r["docs"][0]["file"] == "docs/regulatory/QCB/instructions.md"
        assert "page 1" in r["cites"][0]["label"]

    def test_a_pdf_is_read_page_by_page(self, tmp_path, monkeypatch):
        rl = pytest.importorskip("reportlab.pdfgen.canvas")
        from backend.assistant import regulatory as R
        c = rl.Canvas(str(tmp_path / "rules.pdf"))
        c.drawString(72, 800, "Section 4. A facility more than 90 days past due is credit impaired.")
        c.showPage()
        c.drawString(72, 800, "Section 5. Haircut for commercial real estate collateral.")
        c.save()
        monkeypatch.setattr(R, "REG_DIR", tmp_path)
        monkeypatch.setattr(R, "_CACHE", tmp_path / ".index")
        chunks, _ = R.folder()
        assert [c.section for c in chunks] == ["page 1", "page 2"]
        assert "90 days past due" in chunks[0].text

    def test_an_empty_folder_says_so(self, tmp_path, monkeypatch):
        from backend.assistant import regulatory as R
        from backend.assistant.semantic import reg_documents, regulation
        monkeypatch.setattr(R, "REG_DIR", tmp_path / "none")
        assert "empty" in reg_documents()["summary"]
        r = regulation("QCB default definition")
        assert r["ok"] and "empty" in r["summary"] and r["docs"][0]["link"]["page"] == "frontend/views/help_regulatory.py"

    @pytest.mark.parametrize("q,tools", [
        ("compare the haircuts we apply with QCB and Basel", ["benchmark", "regulation"]),
        ("what does basel say about LGD", ["benchmark", "regulation"]),
        ("is our 60 dpd backstop compliant with IFRS 9", ["benchmark", "regulation"]),
        ("compare our CCF with basel", ["benchmark", "regulation"]),
        ("which regulatory documents do you have", ["reg_documents"]),
        ("How pit pd is calculated", ["explain"]),
        ("whats going on in Al Dhameen", ["explain", "compare"]),
        ("how is Tasdeer treated", ["explain"]),
    ])
    def test_router(self, q, tools):
        from backend.assistant.router import plan
        got = plan(q, None, ["Business Finance", "Al Dhameen", "Tasdeer", "Off BS", "Investments", "Banks and Fis"])
        assert [t for t, _ in got] == tools

    def test_methodology_questions_do_not_pull_the_regulatory_document(self):
        from backend.assistant.knowledge import explain
        for q in ("how is lgd calculated", "How pit pd is calculated", "how is stage 2 decided"):
            assert all(c.source != "regulatory_reference" for c in explain(q))

    def test_a_portfolio_question_leads_with_its_section(self):
        from backend.assistant.knowledge import explain
        assert explain("Al Dhameen portfolio")[0].heading == "16.3 Al Dhameen"
        assert explain("Business Finance portfolio")[0].heading == "16.1 Business Finance"


class TestPortfolioChapter:
    def test_tasdeer_contagion_is_documented_as_the_engine_does_it(self):
        """Section 16.4 says a customer's Tasdeer facility moves its other
        Stage 1 contracts to Stage 2 (the pack says it should not). If the
        engine changes, the document must change with it."""
        from pathlib import Path
        from ifrs9qdb.etl.report import classify_stage_report
        st = classify_stage_report(dpd=[0, 0, 95], default_flag=[0, 0, 0], watchlist=[0, 0, 0],
                                   local_any=[False] * 3, portfolio=["Tasdeer", "Business Finance", "Tasdeer"],
                                   customer=["A", "A", "B"])
        assert list(st) == [2, 2, 3]
        doc = (Path(__file__).resolve().parents[1] / "docs" / "ecl_methodology.md").read_text()
        assert "Tasdeer facility does count as Stage 2 for the sweep" in doc
        assert "Stage 3 when the DPD is above 90" in doc

    def test_each_portfolio_has_its_section(self):
        from pathlib import Path
        import pandas as pd
        import ifrs9qdb
        doc = (Path(__file__).resolve().parents[1] / "docs" / "ecl_methodology.md").read_text()
        ports = pd.read_csv(Path(ifrs9qdb.__file__).resolve().parent / "static" / "portfolios.csv")
        for p in ports["portfolio_code"]:
            assert f"## 16." in doc and f" {p}\n" in doc.replace("## 16.", "\n## 16."), p


class TestFormulasAndLinks:
    """24 Nov 2026: formulas came out broken ("ight),qquad R ... rac{...}")
    because "\\right" and "\\frac" in the model's JSON were read as a carriage
    return and a form feed; sources could not be opened."""

    def test_latex_in_the_models_json_survives(self):
        from backend.assistant.agent import extract_json
        raw = (r'{"action":"final","answer":"$$ \text{SF} = \Phi^{-1}(p) \right) \frac{1}{2} '
               r'\hat g_y + z_s\,\sigma $$\nNext line with \"quotes\" and café"}')
        got = extract_json(raw)["answer"]
        for s in (r"\text{SF}", r"\Phi^{-1}", r"\right)", r"\frac{1}{2}", r"\hat g", r"z_s\,\sigma"):
            assert s in got, s
        assert "\nNext line" in got and '"quotes"' in got and "café" in got
        assert "\r" not in got and "\x0c" not in got and "\t" not in got

    def test_correctly_doubled_latex_and_markdown_escapes_still_work(self):
        from backend.assistant.agent import extract_json
        assert extract_json(r'{"answer":"\\frac{a}{b} and \\Phi"}')["answer"] == r"\frac{a}{b} and \Phi"
        assert extract_json(r'{"action":"tool","tool":"model\_spec","args":{}}')["tool"] == "model_spec"

    def test_citations_become_links_to_the_document_section(self):
        from backend.assistant.links import linkify
        cites = {"k19": {"id": "k19", "kind": "doc", "source": "ecl_methodology",
                         "link": {"page": "frontend/views/help_ecl.py", "ch": "7. Probability of default",
                                  "sec": "7.4 Point-in-time PD and reversion to TTC", "label": "x"}}}
        out = linkify("The PD for years 1 to 5 [k19].", cites)
        assert "[§7.4 ↗](/help_ecl?ch=7.%20Probability%20of%20default&sec=7.4%20Point-in-time" in out

    def test_regulatory_references_become_links_every_time(self):
        from backend.assistant.links import OFFICIAL, linkify
        out = linkify("Cash 0% [CRE22.49; CRE32.11]; currency mismatch 8% (CRE22.52); default B5.5.37.")
        assert out.count(OFFICIAL["CRE22"][1]) == 2 and OFFICIAL["CRE32"][1] in out
        assert OFFICIAL["IFRS9"][1] in out
        assert "[[" not in out                       # the model's brackets are gone

    def test_the_users_own_copy_is_preferred(self):
        from backend.assistant.links import linkify
        out = linkify("See CRE22.49 and QCB Circular 9/2017.",
                      files=["Basel/CRE22.pdf", "QCB/Circular 9-2017 IFRS 9.pdf"])
        assert "regfile://Basel/CRE22.pdf" in out and "regfile://QCB/Circular%209-2017%20IFRS%209.pdf" in out

    def test_a_regulatory_page_citation_opens_the_file_at_the_page(self):
        from backend.assistant.links import cite_url
        lab, url = cite_url({"kind": "reg", "where": "docs/regulatory/QCB/rules.pdf", "section": "page 12"})
        assert url == "regfile://QCB/rules.pdf#page=12"

    def test_the_backend_serves_only_files_in_the_folder(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient
        from backend.assistant import regulatory as R
        from backend.main import app
        (tmp_path / "QCB").mkdir()
        (tmp_path / "QCB" / "rules.pdf").write_bytes(b"%PDF-1.4 test")
        monkeypatch.setattr(R, "REG_DIR", tmp_path)
        c = TestClient(app)
        r = c.get("/api/regulatory/file/QCB/rules.pdf")
        assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
        assert "inline" in r.headers["content-disposition"]
        assert c.get("/api/regulatory/file/../secret.txt").status_code == 404

    def test_benchmark_rows_carry_a_link_to_each_source(self):
        from backend.assistant.semantic import benchmark
        t = benchmark("collateral")["table"]
        row = t["rows"][0]
        assert row["Basel source"].startswith("https://www.bis.org/")

    def test_methodology_answers_show_the_sections_and_the_model_writes_no_formulas(self):
        import backend.assistant.agent as agent
        from backend.assistant.semantic import explain
        p = agent._system_prompt("S", None)
        assert "Do NOT write formulas" in p
        assert all(d["kind"] == "section" for d in explain("How pit pd is calculated")["docs"])


class TestModels:
    """24 Nov 2026: Gemma 4 (31B) on its own gateway, with a key, as the
    default; Gemma 3 stays as an option."""

    @staticmethod
    def _cfg(tmp_path, monkeypatch, env_text=None):
        import shutil
        from pathlib import Path
        import backend.assistant.config as C
        root = Path(__file__).resolve().parents[1]
        shutil.copy(root / "config.yml", tmp_path / "config.yml")
        monkeypatch.setenv("IFRS9_APP_CONFIG", str(tmp_path / "config.yml"))
        for k in ("IFRS9_LLM_ENDPOINT", "IFRS9_LLM_MODEL", "IFRS9_LLM_API_KEY_ENV", "IFRS9_LLM_PROFILE",
                  "QDB_GEMMA4_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setattr(C, "APP_ROOT", tmp_path)
        monkeypatch.chdir(tmp_path)
        if env_text is not None:
            (tmp_path / ".env").write_text(env_text)
        return C

    def test_gemma4_is_the_default(self, tmp_path, monkeypatch):
        C = self._cfg(tmp_path, monkeypatch)
        cfg = C.load_config()
        assert cfg.profile == "gemma4" and cfg.model == "gemma-4-31B-it"
        assert cfg.endpoint == "https://gemma4-api-aicloud.qdb.qa/v1/chat/completions"
        assert cfg.verify_ssl is False and cfg.api_key_env == "QDB_GEMMA4_API_KEY"

    def test_without_its_key_gemma4_says_where_the_key_goes(self, tmp_path, monkeypatch):
        C = self._cfg(tmp_path, monkeypatch)
        why = C.load_config().unavailable_reason()
        assert "QDB_GEMMA4_API_KEY=" in why and ".env" in why
        ms = {m["id"]: m for m in C.list_models()}
        assert ms["gemma4"]["default"] and not ms["gemma4"]["available"]
        assert ms["gemma3"]["available"]

    def test_the_key_is_read_from_dotenv(self, tmp_path, monkeypatch):
        C = self._cfg(tmp_path, monkeypatch, '# keys\nQDB_GEMMA4_API_KEY="sk-vllm-test"\n')
        cfg = C.load_config()
        assert cfg.api_key == "sk-vllm-test" and cfg.unavailable_reason() is None

    def test_gemma3_can_still_be_picked(self, tmp_path, monkeypatch):
        C = self._cfg(tmp_path, monkeypatch)
        cfg = C.load_config("gemma3")
        assert cfg.model == "unsloth/gemma-3-12b-it" and cfg.verify_ssl is True
        assert cfg.unavailable_reason() is None

    def test_the_call_sends_the_key_and_skips_the_certificate_check(self, tmp_path, monkeypatch):
        C = self._cfg(tmp_path, monkeypatch, "QDB_GEMMA4_API_KEY=sk-vllm-test\n")
        import backend.assistant.client as client
        seen = {}

        class R:
            status_code = 200
            text = ""

            def json(self):
                return {"choices": [{"message": {"content": '<think>working</think>{"action":"final"}'}}]}

        def post(url, json, headers, timeout, verify):
            seen.update(url=url, model=json["model"], auth=headers.get("Authorization"), verify=verify)
            return R()
        monkeypatch.setattr(client.requests, "post", post)
        out = client.chat([{"role": "user", "content": "hi"}], C.load_config())
        assert seen == {"url": "https://gemma4-api-aicloud.qdb.qa/v1/chat/completions", "model": "gemma-4-31B-it",
                        "auth": "Bearer sk-vllm-test", "verify": False}
        assert out == '{"action":"final"}'

    def test_a_ca_file_path_turns_the_check_on(self):
        from backend.assistant.client import _verify
        assert _verify(AssistantConfig(verify_ssl="C:/certs/qdb.pem")) == "C:/certs/qdb.pem"
        assert _verify(AssistantConfig(verify_ssl=True)) is True

    def test_dotenv_and_keys_are_never_committed(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        assert ".env" in (root / ".gitignore").read_text().split()
        assert "sk-vllm-xxxxxx" in (root / ".env.example").read_text()


class TestRunLine:
    """Every answer from run data says which run it is about."""

    def test_answer_names_its_run(self, monkeypatch):
        from backend.assistant import agent as A
        from backend.assistant import semantic as S
        monkeypatch.setattr(S, "_runs", lambda: [
            {"run_id": "run_00002", "run_type": "official", "portfolio_date": "2026-09-30"},
            {"run_id": "run_00001", "run_type": "unofficial", "portfolio_date": "6/30/2026"}])

        def fake(focus=None, **_):
            S.resolve_run(None, focus)
            S.resolve_run("previous", focus)
            return {"ok": True, "summary": "x"}
        monkeypatch.setitem(S.TOOLS, "fake_lookup", fake)
        res = A.execute("fake_lookup", {}, "run_00002")
        assert res["runs_used"] == ["run_00002", "run_00001"]
        out = A._result("x", {"k1": res}, [], None, "q")
        assert [r["run_id"] for r in out["runs"]] == ["run_00001", "run_00002"]
        assert out["runs"][1]["run_type"] == "Official"
        assert out["runs"][1]["quarter"] == "Q3 2026"
        assert out["runs"][0]["quarter"] == "Q2 2026"

    def test_a_document_answer_names_no_run(self):
        from backend.assistant import agent as A
        out = A._result("x", {"k1": {"ok": True, "summary": "doc"}}, [], None, "q")
        assert out["runs"] == []
