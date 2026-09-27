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
        stub = _Stub(['{"action":"tool","tool":"list_runs","args":{}}'] * 3
                     + ['{"action":"final","answer":"done"}'])
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
