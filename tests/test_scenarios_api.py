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

OIL = {"name": "Oil", "shocks": [{"concept": "OIL_PRICE", "size": -40, "shape": "one_year"}]}


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    if not FIX.is_dir():
        pytest.skip("the engine's test store is not next to the installed package")
    d = tmp_path / "store"
    shutil.copytree(FIX, d)
    monkeypatch.setattr(macro_routes, "MACRO_STORE_DIR", d)
    monkeypatch.setattr(scn_routes, "STRESS_SCENARIOS_FILE", tmp_path / "stress_scenarios.yml")
    scn_routes._CACHE.clear()
    yield d
    scn_routes._CACHE.clear()


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
    def test_setup(self):
        b = client.get("/api/scenarios/setup").json()
        assert len(b["library"]) == 8 and b["horizon"] == 5
        assert "OIL_PRICE" in b["var_concepts"]

    def test_no_shock_is_no_move_and_a_shock_keeps_its_path(self):
        b = client.post("/api/scenarios/preview",
                        json={"scenario": {"name": "Nothing"}, "first_year": 2026}).json()
        assert b["paths"] == [] and b["severity"]["distance"] == 0
        b = client.post("/api/scenarios/preview", json={"scenario": OIL, "first_year": 2026}).json()
        oil = next(p for p in b["paths"] if p["concept"] == "OIL_PRICE")
        assert oil["given"] and oil["2026"] == -40 and oil["2027"] == 0
        assert b["severity"]["distance"] > 0

    def test_saved_scenarios_round_trip(self):
        r = client.put("/api/scenarios/saved", json={"scenarios": [OIL]})
        assert r.json()["saved"] == 1
        back = client.get("/api/scenarios/saved").json()
        assert back[0]["name"] == "Oil" and back[0]["shocks"][0]["size"] == -40

    @needs_run
    def test_an_empty_scenario_is_the_runs_provision(self):
        b = client.post(f"/api/scenarios/{RUN}/run", json={"scenario": {"name": "Nothing"}}).json()
        assert abs(b["delta"]) < 1e-6

    @needs_run
    def test_a_scenario_is_the_engines_transmit(self):
        from ifrs9qdb.stresstest import transmit
        b = client.post(f"/api/scenarios/{RUN}/run", json={"scenario": OIL}).json()
        rc, _, _ = scn_routes._rc(RUN, None)
        assert b["delta"] == pytest.approx(transmit(rc, OIL)["delta"], rel=1e-12)
        assert b["delta"] > 0
        assert sum(w["change"] for w in b["waterfall"]) == pytest.approx(b["delta"], rel=1e-9)

    @needs_run
    def test_compare_prices_each_on_its_own(self):
        b = client.post(f"/api/scenarios/{RUN}/compare",
                        json={"scenarios": [OIL, {"name": "Nothing"}]}).json()
        ch = {r["scenario"]: r["change"] for r in b["table"]}
        assert abs(ch["Nothing"]) < 1e-6 and ch["Oil"] > 0
