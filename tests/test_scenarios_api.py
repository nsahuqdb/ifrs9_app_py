"""The macro data and scenario stress endpoints.

Each is a call to ifrs9qdb.macro or ifrs9qdb.stresstest; these check that the
endpoint returns what the engine returns and that an empty scenario changes
nothing. The macro store is the engine's synthetic test store, copied; the
pricing tests run against whatever ``IFRS9_RUNS_DIR`` points at and skip when
that is nothing.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import ifrs9qdb
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.routes import macro as macro_routes
from backend.routes import scenarios as scn_routes

client = TestClient(app)
FIX = Path(ifrs9qdb.__file__).resolve().parents[2] / "tests" / "fixtures" / "macro" / "store"

RUNS = [r["run_id"] for r in client.get("/api/runs").json() if r.get("has_report")]
RUN = RUNS[0] if RUNS else None
needs_run = pytest.mark.skipif(RUN is None, reason="set IFRS9_RUNS_DIR")

OIL = {"name": "Oil", "main": {"OIL_PRICE": [-40, None, None, None, None]},
       "description": "Oil falls 40%.", "history": "Sized on 2009.",
       "narrative": "Oil falls in Y1 and the rest follows.",
       "why": {"OIL_PRICE": "The 2009 fall."}}
ENGINE_TESTS = FIX.parents[2]


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    if not FIX.is_dir():
        pytest.skip("the engine's test store is not next to the installed package")
    d = tmp_path / "store"
    shutil.copytree(FIX, d)
    monkeypatch.setattr(macro_routes, "MACRO_STORE_DIR", d)
    monkeypatch.setattr(scn_routes, "SCENARIOS_DB", tmp_path / "scenarios.sqlite")
    scn_routes._CACHE.clear()
    yield d
    scn_routes._CACHE.clear()


@pytest.fixture
def system_store(tmp_path, monkeypatch):
    """The engine's synthetic store with every series the linked effects
    read."""
    import sys
    sys.path.insert(0, str(ENGINE_TESTS))
    from system_store import build
    d = tmp_path / "sys_store"
    build(d)
    monkeypatch.setattr(macro_routes, "MACRO_STORE_DIR", d)
    scn_routes._CACHE.clear()
    return d


class TestMacro:
    def test_status_lists_the_vintage_and_resolves_the_concepts(self):
        b = client.get("/api/macro/status").json()
        assert b["latest"] == "v-fixture"
        got = {c["concept"]: c["series_id"] for c in b["concepts"]}
        assert got["NONOIL_GDP_QAT"] == "IMF:REO_MCD:QAT:NGDP_NOIL_RPCH:A"

    def test_search(self):
        hits = client.get("/api/macro/search", params={"q": "brent"}).json()
        assert any(h["series_id"].startswith("IMF:PCPS:W00:POILBRE") for h in hits)

    def test_a_proposal_follows_the_five_year_rule(self):
        r = client.post("/api/macro/propose", json={"reporting_date": "2026-09-30"})
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["years"] == [2026, 2027, 2028, 2029, 2030]
        assert all(c["ok"] for c in b["checks"])

    def test_apply_needs_a_draft_named(self):
        r = client.post("/api/macro/apply", json={"reporting_date": "2026-09-30"})
        assert r.status_code == 400


class TestScenarios:
    def test_setup(self, system_store):
        b = client.get("/api/scenarios/setup").json()
        assert len(b["library"]) >= 14 and b["horizon"] == 5
        assert b["first_year"] == 2026
        assert {v["variable"] for v in b["variables"]} >= {"OIL_PRICE", "NONOIL_GDP_QAT"}

    def test_main_years_hold_and_the_rest_are_linked(self, system_store):
        b = client.post("/api/scenarios/preview", json={"scenario": OIL}).json()
        oil = [p for p in b["paths"] if p["variable"] == "OIL_PRICE"]
        assert oil[0]["move"] == -40 and oil[0]["role"] == "main" and oil[0]["set"]
        gx = [p for p in b["paths"] if p["variable"] == "GOV_SPEND_QAT"]
        assert gx[0]["role"] == "linked" and gx[0]["move"] < 0
        assert "GOV_SPEND_QAT" in b["recommended"]
        off = client.post("/api/scenarios/preview",
                          json={"scenario": {**OIL, "linked": []}}).json()
        assert all(p["move"] == 0 for p in off["paths"] if p["variable"] != "OIL_PRICE")

    def test_saving_needs_the_reasons(self, system_store):
        bare = {"name": "Bare", "main": {"OIL_PRICE": [-40, None, None, None, None]}}
        r = client.post("/api/scenarios/saved", json={"scenario": bare})
        assert r.status_code == 400 and "what it captures" in r.json()["detail"]
        r = client.post("/api/scenarios/saved",
                        json={"scenario": {**OIL, "why": {}}})
        assert r.status_code == 400 and "why OIL_PRICE" in r.json()["detail"]

    def test_saving_new_versions_and_deleting(self, system_store):
        r = client.post("/api/scenarios/saved", json={"scenario": OIL})
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        again = client.post("/api/scenarios/saved", json={"scenario": OIL})
        assert again.status_code == 400                         # names are unique
        lib = client.post("/api/scenarios/saved",
                          json={"scenario": {**OIL, "name": "2015–16 oil collapse"}})
        assert lib.status_code == 400                           # a library name is taken
        edited = {**OIL, "main": {"OIL_PRICE": [-50, None, None, None, None]}}
        r = client.put(f"/api/scenarios/saved/{sid}", json={"scenario": edited})
        assert r.json()["main"]["OIL_PRICE"][0] == -50
        assert [h["action"] for h in client.get(f"/api/scenarios/saved/{sid}/history").json()] \
            == ["created", "updated"]
        client.delete(f"/api/scenarios/saved/{sid}")
        assert client.get("/api/scenarios/saved").json() == []

    def test_the_history_behind_a_library_scenario(self, system_store):
        b = client.get("/api/scenarios/library/H4/history").json()
        assert b["episode"] == [2015, 2017]
        assert {r["variable"] for r in b["series"]} >= {"OIL_PRICE", "GDP_WLD"}

    def test_a_shock_is_derived_and_explained(self, system_store):
        d = client.get("/api/scenarios/library/H1/derivation").json()["rows"]
        w = [r for r in d if r["variable"] == "GDP_WLD"]
        assert w[0]["year"] == 1986 and w[0]["reference_year"] == 1985
        assert w[0]["shock"] == -0.29                            # the library's number
        assert isinstance(w[0]["recorded"], float) and isinstance(w[0]["reference"], float)
        b = client.post("/api/scenarios/preview", json={"scenario": OIL}).json()
        ex = b["explain"]
        gx = sum(r["part"] for r in ex if r["variable"] == "GOV_SPEND_QAT" and r["year"] == 1)
        p = next(r for r in b["paths"] if r["variable"] == "GOV_SPEND_QAT")
        assert gx == pytest.approx(p["move"])

    def test_the_system_table(self, system_store):
        b = client.get("/api/scenarios/system").json()
        assert any(r["driver"] == "World GDP growth" for r in b["table"])
        assert len(b["library_check"]) > 10

    @needs_run
    def test_an_empty_scenario_is_the_runs_provision(self, system_store):
        b = client.post(f"/api/scenarios/{RUN}/price", json={"scenario": {"name": "Nothing"}}).json()
        assert abs(b["delta"]) < 1e-6

    @needs_run
    def test_a_scenario_is_the_engines_transmit(self, system_store):
        from ifrs9qdb.stresstest import transmit
        b = client.post(f"/api/scenarios/{RUN}/price", json={"scenario": OIL}).json()
        rc, _, _ = scn_routes._rc(RUN, None)
        assert b["delta"] == pytest.approx(transmit(rc, OIL)["delta"], rel=1e-12)
        assert sum(w["change"] for w in b["waterfall"]) == pytest.approx(b["delta"], rel=1e-9)

    @needs_run
    def test_compare_prices_each_on_its_own(self, system_store):
        b = client.post(f"/api/scenarios/{RUN}/compare",
                        json={"scenarios": [OIL, {"name": "Nothing"}]}).json()
        ch = {r["scenario"]: r["change"] for r in b["table"]}
        assert abs(ch["Nothing"]) < 1e-6 and ch["Oil"] != 0
