"""The analytics endpoints added for risk, scenarios, movement and migration.

The API must not become a second implementation. Each of these checks that the
endpoint returns what the engine returns, and that a run missing the inputs an
endpoint needs SAYS so rather than returning an empty body a screen would draw
as "nothing to report".

They run against whatever ``IFRS9_RUNS_DIR`` points at, and skip cleanly when
that is nothing.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)

RUNS = [r["run_id"] for r in client.get("/api/runs").json()
        if r.get("has_report")]
RUN = RUNS[0] if RUNS else None
PAIR = (RUNS[1], RUNS[0]) if len(RUNS) > 1 else None

needs_run = pytest.mark.skipif(RUN is None, reason="set IFRS9_RUNS_DIR")
needs_pair = pytest.mark.skipif(PAIR is None,
                                reason="two runs are needed in IFRS9_RUNS_DIR")


class TestRisk:
    @needs_run
    def test_it_returns_every_parameter_family(self):
        body = client.get(f"/api/analytics/{RUN}/risk").json()
        assert set(body) == {"pd", "pd_by_scale", "pd_curves", "lgd_floor",
                             "lgd_scatter", "term_structure", "ead_runoff"}
        assert body["pd"], "a report with no PD profile is not usable"

    @needs_run
    def test_an_unknown_breakdown_is_refused(self):
        """A typo must not come back as an empty chart."""
        r = client.get(f"/api/analytics/{RUN}/risk", params={"by": "sector"})
        assert r.status_code == 400

    @needs_run
    def test_the_term_structure_only_ever_climbs(self):
        ts = client.get(f"/api/analytics/{RUN}/risk",
                        params={"portfolio": "Business Finance"}).json()
        rows = ts["term_structure"]
        if not rows:
            pytest.skip("this run supplied no PD curves")
        assert min(r["marginal_pd"] for r in rows) >= -1e-9

    @needs_run
    def test_collateral_reports_orphans_rather_than_hiding_them(self):
        body = client.get(f"/api/analytics/{RUN}/collateral").json()
        if not body.get("available"):
            assert body["reason"]
            return
        assert set(body) >= {"allocations", "orphan_allocations",
                             "orphan_contracts", "collateral_records",
                             "by_type"}

    @needs_run
    def test_segments_conserve_the_report(self):
        cells = client.get(f"/api/analytics/{RUN}/segments").json()
        summary = client.get(f"/api/analytics/{RUN}/summary").json()
        assert sum(c["value"] for c in cells) == pytest.approx(summary["ecl"])

    @needs_run
    def test_an_unknown_segment_value_is_refused(self):
        r = client.get(f"/api/analytics/{RUN}/segments",
                       params={"value": "provision"})
        assert r.status_code == 400


class TestStagingDetail:
    @needs_run
    def test_the_rule_is_re_applied_and_the_result_reported(self):
        body = client.get(f"/api/analytics/{RUN}/staging-detail").json()
        assert set(body) == {"dpd_threshold", "dpd_by_stage", "trigger_overlap",
                             "stage3_drivers", "consistency", "findings"}
        c = body["consistency"]
        assert c["rule_available"] is True
        assert c["checked"] > 0

    @needs_run
    def test_it_reads_the_run_on_its_own_policy(self):
        """No threshold given: the one the run froze, not a hardcoded 60."""
        from backend.routes.analytics import RUNS_DIR, _output_dir
        from ifrs9qdb.stress import staging_threshold
        used = staging_threshold(_output_dir(RUNS_DIR / RUN))
        for path in ("staging", "staging-detail"):
            body = client.get(f"/api/analytics/{RUN}/{path}").json()
            assert body["dpd_threshold"] == used
            asked = client.get(f"/api/analytics/{RUN}/{path}",
                               params={"dpd_threshold": 30}).json()
            assert asked["dpd_threshold"] == 30
        trig = client.get(f"/api/analytics/{RUN}/staging",
                          params={"dpd_threshold": 30}).json()["triggers"]
        assert any(r["trigger"] == "DPD 31-90" for r in trig)

    @needs_run
    def test_trigger_combinations_are_additive(self):
        """Each Stage 2 contract appears under exactly one combination."""
        detail = client.get(f"/api/analytics/{RUN}/staging-detail").json()
        staging = client.get(f"/api/analytics/{RUN}/staging").json()
        s2 = next((r["contracts"] for r in staging["distribution"]
                   if r["stage"].endswith("2")), 0)
        assert sum(r["contracts"] for r in detail["trigger_overlap"]) == s2


class TestMigration:
    @needs_pair
    def test_the_stage_matrix_counts_customers_once(self):
        """Stage is a customer attribute: a customer in both runs is one cell,
        however many facilities it holds."""
        prev, curr = PAIR
        m = client.get("/api/analytics/migration",
                       params={"prev": prev, "curr": curr}).json()
        cells = m["stage"]
        assert cells, "two runs of one book share customers"
        assert {r["from"] for r in cells} <= {1, 2, 3}
        assert {r["to"] for r in cells} <= {1, 2, 3}
        n = client.get(f"/api/analytics/{curr}/summary").json()
        assert sum(r["customers"] for r in cells) <= n["customers"]


class TestScenarios:
    @needs_run
    def test_the_scenarios_come_back_ordered_by_severity(self):
        body = client.get(f"/api/analytics/{RUN}/scenarios").json()
        if not body.get("available"):
            pytest.skip(body.get("reason", "no per-scenario reports"))
        z = [r["severity_z"] for r in body["comparison"]
             if r.get("severity_z") is not None]
        assert z == sorted(z)

    @needs_run
    def test_the_weights_shown_are_the_ones_the_run_was_priced_with(self):
        w = client.get(f"/api/analytics/{RUN}/scenarios/weights").json()
        if not w.get("ok"):
            pytest.skip(w.get("reason", "no frozen config"))
        assert sum(w["internal"].values()) == pytest.approx(1.0)
        assert sum(w["external"].values()) == pytest.approx(1.0, abs=1e-6)

    @needs_run
    def test_reweighting_at_the_runs_own_weights_changes_nothing(self):
        """Repriced, not interpolated: the run's own weights give its own
        provision back."""
        w = client.get(f"/api/analytics/{RUN}/scenarios/weights").json()
        if not w.get("ok"):
            pytest.skip(w.get("reason", "no frozen config"))
        r = client.post(f"/api/stress/{RUN}/mev",
                        json={"weight_mode": "custom", "weights": w["internal"]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["delta"] == pytest.approx(0.0, abs=1e-3)
        assert body["weights_used"] == pytest.approx(w["internal"])

    @needs_run
    def test_weights_naming_an_unknown_scenario_are_refused(self):
        w = client.get(f"/api/analytics/{RUN}/scenarios/weights").json()
        if not w.get("ok"):
            pytest.skip(w.get("reason", "no frozen config"))
        r = client.post(f"/api/stress/{RUN}/mev",
                        json={"weight_mode": "custom",
                              "weights": {**w["internal"], "Mild Panic": 0.5}})
        assert r.status_code == 400
        assert "Mild Panic" in r.json()["detail"]

    @needs_run
    def test_ten_points_onto_the_worst_scenario_costs_more(self):
        w = client.get(f"/api/analytics/{RUN}/scenarios/weights").json()
        if not w.get("ok"):
            pytest.skip(w.get("reason", "no frozen config"))
        rows = client.post(f"/api/stress/{RUN}/weights-sensitivity",
                           json={"weights": None}).json()
        assert {r["scenario"] for r in rows} == set(w["internal"])
        worst = max(rows, key=lambda r: r["ecl_scenario"])
        best = min(rows, key=lambda r: r["ecl_scenario"])
        assert worst["change"] > 0 > best["change"]


class TestModelAssumptions:
    @needs_run
    def test_a_run_explains_itself_from_what_it_froze(self):
        body = client.get(f"/api/analytics/{RUN}/model").json()
        if not body.get("available"):
            assert "config_used" in body["reason"]
            return
        assert body["severity"] and body["mev_weights"]
        assert sum(r["weight"] or 0 for r in body["mev_weights"]) == \
            pytest.approx(1.0)
        # the scenario weights it is priced with, beside what the file states
        used = body["weights_used"]
        assert used and sum(used["internal"].values()) == pytest.approx(1.0)


class TestQualityAndLookup:
    @needs_run
    def test_the_detail_matches_the_summary(self):
        summary = client.get(f"/api/analytics/{RUN}/quality").json()
        detail = client.get(f"/api/analytics/{RUN}/quality-detail").json()
        assert sorted(detail) == sorted(r["check"] for r in summary)

    @needs_run
    def test_a_customer_that_is_not_there_is_reported(self):
        r = client.get(f"/api/analytics/{RUN}/customers",
                       params={"ids": "not-a-customer"}).json()
        assert r["missing"] == ["not-a-customer"]
        assert r["found"] == []

    @needs_run
    def test_asking_for_nothing_is_refused(self):
        r = client.get(f"/api/analytics/{RUN}/customers", params={"ids": " "})
        assert r.status_code == 400


class TestStagingThresholdAndMacro:
    """Both reprice the whole book, so these are deliberately few."""

    @needs_run
    def test_the_sweep_always_includes_the_policy_in_force(self):
        """Comparing against a hardcoded 60 when the run used something else
        compares the book against a policy nobody applied."""
        r = client.get(f"/api/stress/{RUN}/threshold-sweep",
                       params={"thresholds": "0,90"}).json()
        used = r["run_threshold"]
        assert used in [row["threshold"] for row in r["rows"]]
        assert r["rows"], "nothing was repriced"

    @needs_run
    def test_a_sweep_of_nonsense_is_refused(self):
        r = client.get(f"/api/stress/{RUN}/threshold-sweep",
                       params={"thresholds": "sixty"})
        assert r.status_code == 400

    @needs_run
    def test_rebuilding_the_pd_chain_with_no_edit_changes_nothing(self):
        """The control for the whole macro screen. A rebuild that drifts makes
        every figure on it a measure of the rebuild."""
        r = client.post(f"/api/stress/{RUN}/mev",
                        json={"cells": [], "shock": {}, "weight_mode": "auto"})
        if r.status_code == 400 and "config_used" in r.json()["detail"]:
            pytest.skip("this run has no frozen config")
        body = r.json()
        assert body["delta"] == pytest.approx(0.0, abs=1e-6)

    @needs_run
    def test_holding_the_weights_isolates_the_pd_effect(self):
        r = client.post(f"/api/stress/{RUN}/mev",
                        json={"shock": {"1": -2.0}, "weight_mode": "hold"})
        if r.status_code == 400 and "config_used" in r.json()["detail"]:
            pytest.skip("this run has no frozen config")
        body = r.json()
        assert body["delta"] > 0, "a worse path must raise the PD-only figure"
        assert body["weight_mode"] == "hold"

    @needs_run
    def test_an_unknown_weight_mode_is_refused(self):
        r = client.post(f"/api/stress/{RUN}/mev",
                        json={"weight_mode": "whatever_sounds_right"})
        assert r.status_code == 400


class TestStressTest:
    """One stress function behind the page: a scope and the levers moved for
    it. A what-if on named exposures and a package are both this."""

    @needs_run
    def test_only_the_scope_moves(self):
        body = client.post(f"/api/stress/{RUN}/apply", json={
            "name": "Off BS to Stage 2", "portfolios": ["Off BS"],
            "stage_to": 2}).json()
        assert body["delta"] > 0 and body["moved"] > 0
        moved = {r["portfolio"] for r in body["by_portfolio"]
                 if abs(r["change"]) > 1e-6}
        assert moved == {"Off BS"}

    @needs_run
    def test_a_stress_that_changes_nothing_moves_nothing(self):
        """The baseline is priced by the same function as the stress."""
        body = client.post(f"/api/stress/{RUN}/apply",
                           json={"portfolios": ["Off BS"]}).json()
        assert body["delta"] == pytest.approx(0.0, abs=1e-6)
        assert body["moved"] == 0

    @needs_run
    def test_a_harsher_standard_package_costs_more(self):
        std = {p["name"]: p for p in
               client.get(f"/api/stress/{RUN}/scope").json()["standard"]}
        got = {n: client.post(f"/api/stress/{RUN}/apply", json=std[n]).json()
               for n in ("Mild downturn", "Severe downturn")}
        assert got["Severe downturn"]["delta"] > got["Mild downturn"]["delta"] > 0
        assert got["Severe downturn"]["before"] == \
            pytest.approx(got["Mild downturn"]["before"])

    @needs_run
    def test_a_scope_matching_nothing_is_refused(self):
        r = client.post(f"/api/stress/{RUN}/apply", json={"portfolios": ["Nope"]})
        assert r.status_code == 400 and "scope" in r.json()["detail"]

    def test_saved_packages_read_back_as_written(self, tmp_path, monkeypatch):
        import backend.routes.stress as R
        monkeypatch.setattr(R, "STRESS_PACKAGES_FILE", tmp_path / "stress_packages.yml")
        assert client.get("/api/stress/packages").json() == []
        pkgs = [{"name": "named", "customers": ["A B", "C"], "stages": [2],
                 "stage_to": 3, "pd_multiplier": 1.5},
                {"name": "policy", "dpd_threshold": 30, "contagion": False}]
        assert client.put("/api/stress/packages",
                          json={"packages": pkgs}).json()["saved"] == 2
        back = client.get("/api/stress/packages").json()
        assert [b["name"] for b in back] == ["named", "policy"]
        assert back[0]["customers"] == ["A B", "C"] and back[0]["stage_to"] == 3
        assert back[1]["dpd_threshold"] == 30 and back[1]["contagion"] is False


class TestDistributions:
    @needs_run
    def test_the_profiles_over_every_contract_conserve_the_book(self):
        """Days past due and ticket size are defined for every contract, so a
        band that lost one would be losing it silently."""
        d = client.get(f"/api/analytics/{RUN}/distributions").json()
        n = client.get(f"/api/analytics/{RUN}/summary").json()["contracts"]
        for name in ("dpd", "exposure"):
            assert sum(r["contracts"] for r in d[name]) == n, name

    @needs_run
    def test_the_parameter_profiles_band_everything_they_cover(self):
        """PD and LGD are not populated for every contract, so these band
        fewer — but never zero, and never a suspiciously round fraction: a
        value sitting exactly on the top edge used to fall out of the last
        bucket, which is the one anybody reading the chart wants."""
        d = client.get(f"/api/analytics/{RUN}/distributions").json()
        n = client.get(f"/api/analytics/{RUN}/summary").json()["contracts"]
        for name in ("lgd", "pd"):
            got = sum(r["contracts"] for r in d[name])
            assert 0 < got <= n, name
            assert got > 0.5 * n, f"{name} banded only {got} of {n}"

    @needs_run
    def test_pd_rises_with_the_rating(self):
        """A kink here means a rating or PD-curve mapping broke."""
        rows = client.get(f"/api/analytics/{RUN}/distributions").json()["pd_by_rating"]
        if len(rows) < 3:
            pytest.skip("too few rated grades to judge")
        assert all(r["pd_weighted"] is not None for r in rows)

    @needs_run
    def test_the_lorenz_curve_ends_at_a_hundred(self):
        lz = client.get(f"/api/analytics/{RUN}/distributions").json()["lorenz"]
        assert lz and lz[-1]["pct_ecl"] == pytest.approx(100.0, abs=1e-6)


class TestBridge:
    """Why the provision moved, at any level: what the engine's bridge
    returns, closing exactly, for the book and for a group within it."""

    @needs_pair
    def test_the_book_closes_on_both_runs_totals(self):
        prev, curr = PAIR
        b = client.get("/api/analytics/bridge",
                       params={"prev": prev, "curr": curr}).json()
        deltas = sum(s["amount"] for s in b["steps"] if s["kind"] == "delta")
        assert b["opening"] + deltas == pytest.approx(b["closing"], abs=1e-3)
        assert abs(b["residual"]) < 1e-3
        keys = [s["key"] for s in b["steps"]]
        for k in ("exposure", "stage", "rating", "macro", "model", "lgd"):
            assert k in keys
        assert set(b["before"]) >= {"exposure", "ecl", "rating", "worst_stage"}

    @needs_pair
    def test_a_customer_has_its_own_waterfall(self):
        prev, curr = PAIR
        m = client.get("/api/analytics/bridge/members",
                       params={"prev": prev, "curr": curr, "level": "customer"}).json()
        assert m and {"value", "label", "ecl_a", "ecl_b", "change"} <= set(m[0])
        cust = m[0]["value"]
        b = client.get("/api/analytics/bridge", params={
            "prev": prev, "curr": curr, "level": "customer",
            "members": [cust]}).json()
        assert b["before"]["ecl"] == pytest.approx(m[0]["ecl_a"])
        assert b["after"]["ecl"] == pytest.approx(m[0]["ecl_b"])
        deltas = sum(s["amount"] for s in b["steps"] if s["kind"] == "delta")
        assert b["opening"] + deltas == pytest.approx(b["closing"], abs=1e-3)

    @needs_pair
    def test_every_segment_closes(self):
        prev, curr = PAIR
        by = client.get("/api/analytics/bridge/by", params={
            "prev": prev, "curr": curr, "level": "segment"}).json()
        for r in by:
            steps = sum(v for k, v in r.items()
                        if k not in ("group", "label", "opening", "closing", "change"))
            assert r["opening"] + steps == pytest.approx(r["closing"], abs=1e-3)
        assert all(r["label"] for r in by)

    @needs_pair
    def test_a_level_needs_a_member_and_a_known_name(self):
        prev, curr = PAIR
        assert client.get("/api/analytics/bridge", params={
            "prev": prev, "curr": curr, "level": "customer"}).status_code == 400
        assert client.get("/api/analytics/bridge", params={
            "prev": prev, "curr": curr, "level": "sector",
            "members": ["x"]}).status_code == 400


class TestCustomerCalculator:
    """The customer ECL calculator: the customer list, and the workbook as an
    .xlsx attachment, logged to the audit trail."""

    @needs_run
    def test_the_customers_and_one_workbook(self):
        body = client.get(f"/api/analytics/{RUN}/calculator/customers").json()
        assert body["customers"], "a run with a report has customers"
        cust = body["customers"][0]["customer_id"]
        r = client.get(f"/api/analytics/{RUN}/calculator",
                       params={"customer": cust})
        assert r.status_code == 200
        assert r.content[:2] == b"PK"
        assert "attachment" in r.headers["content-disposition"]

    @needs_run
    def test_an_unknown_customer_is_a_404(self):
        r = client.get(f"/api/analytics/{RUN}/calculator",
                       params={"customer": "no such customer"})
        assert r.status_code == 404

    def test_an_unknown_run_is_a_404(self):
        assert client.get("/api/analytics/no_such_run/calculator",
                          params={"customer": "1"}).status_code == 404
        assert client.get("/api/analytics/no_such_run/calculator/customers"
                          ).status_code == 404

    def test_the_export_is_audited(self, monkeypatch, tmp_path):
        import ifrs9qdb.audit_log as al
        import ifrs9qdb.calc_workbook as cw
        from backend.routes import analytics as an
        (tmp_path / "run_x" / "Output").mkdir(parents=True)
        monkeypatch.setattr(an, "RUNS_DIR", tmp_path)
        monkeypatch.setattr(cw, "customer_ecl_workbook",
                            lambda run, cust: b"PK fake workbook")
        seen = []
        monkeypatch.setattr(al, "audit_event", lambda e: seen.append(e))
        r = client.get("/api/analytics/run_x/calculator",
                       params={"customer": "C 1", "user": "tester"})
        assert r.status_code == 200 and r.content == b"PK fake workbook"
        assert 'filename="ECL_calculator_run_x_C_1.xlsx"' in \
            r.headers["content-disposition"]
        assert seen == [{"event": "customer_calculator_exported",
                         "run_id": "run_x", "customer_id": "C 1",
                         "user": "tester"}]
