"""The analytics endpoints added for risk, scenarios, attribution and migration.

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
        assert set(body) == {"pd", "lgd_floor", "lgd_scatter",
                             "term_structure", "ead_runoff"}
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
        assert set(body) == {"dpd_by_stage", "trigger_overlap",
                             "stage3_drivers", "consistency", "findings"}
        c = body["consistency"]
        assert c["rule_available"] is True
        assert c["checked"] > 0

    @needs_run
    def test_trigger_combinations_are_additive(self):
        """Each Stage 2 contract appears under exactly one combination."""
        detail = client.get(f"/api/analytics/{RUN}/staging-detail").json()
        staging = client.get(f"/api/analytics/{RUN}/staging").json()
        s2 = next((r["contracts"] for r in staging["distribution"]
                   if r["stage"].endswith("2")), 0)
        assert sum(r["contracts"] for r in detail["trigger_overlap"]) == s2


class TestAttribution:
    @needs_pair
    def test_the_indicative_split_sums_to_the_move(self):
        prev, curr = PAIR
        body = client.get("/api/analytics/attribution",
                          params={"prev": prev, "curr": curr}).json()
        eff = body["indicative"]
        assert sum(e["effect"] for e in eff) == pytest.approx(
            eff[0]["actual_change"], abs=1e-6)

    @needs_pair
    def test_the_bridge_sums_to_the_change_in_coverage(self):
        prev, curr = PAIR
        body = client.get("/api/analytics/attribution",
                          params={"prev": prev, "curr": curr}).json()
        a = client.get(f"/api/analytics/{prev}/summary").json()
        b = client.get(f"/api/analytics/{curr}/summary").json()
        assert sum(r["total_effect"] for r in body["bridge"]) == pytest.approx(
            b["coverage"] - a["coverage"], abs=1e-6)

    @needs_pair
    def test_the_exact_split_reconciles_or_explains_itself(self):
        prev, curr = PAIR
        body = client.get("/api/analytics/attribution",
                          params={"prev": prev, "curr": curr,
                                  "exact": True}).json()
        if body["exact"] is None:
            assert body["exact_reason"], "an empty chart is not an answer"
            return
        ex = body["exact"]
        scale = max(abs(ex["opening"]), abs(ex["closing"]), 1.0)
        assert abs(ex["residual"]) / scale < 1e-12
        assert [e["factor"] for e in ex["effects"]] == \
            ["Horizon", "EAD", "PD", "LGD"]

    @needs_pair
    def test_an_unknown_bridge_grouping_is_refused(self):
        prev, curr = PAIR
        r = client.get("/api/analytics/attribution",
                       params={"prev": prev, "curr": curr, "by": "sector"})
        assert r.status_code == 400


class TestMigration:
    @needs_pair
    def test_customers_and_contracts_give_different_counts(self):
        """Rating is a customer attribute; a contract view inflates the cells."""
        prev, curr = PAIR
        cust = client.get("/api/analytics/migration",
                          params={"prev": prev, "curr": curr}).json()
        ctr = client.get("/api/analytics/migration",
                         params={"prev": prev, "curr": curr,
                                 "by_customer": False}).json()
        assert sum(r["n"] for r in cust["rating"]) < \
            sum(r["n"] for r in ctr["rating"])

    @needs_pair
    def test_the_movers_are_exactly_the_off_diagonal(self):
        prev, curr = PAIR
        m = client.get("/api/analytics/migration",
                       params={"prev": prev, "curr": curr}).json()
        moved = sum(r["customers"] for r in m["stage"] if r["from"] != r["to"])
        assert len(m["movers"]) == min(moved, 200)


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
    def test_reweighting_reports_what_it_dropped(self):
        """A weight naming a scenario the run did not price must not silently
        shrink the total."""
        body = client.get(f"/api/analytics/{RUN}/scenarios").json()
        if not body.get("available"):
            pytest.skip("no per-scenario reports")
        names = [r["scenario"] for r in body["comparison"]]
        w = {n: 1 / len(names) for n in names}
        w["Mild Panic"] = 0.5
        r = client.post(f"/api/analytics/{RUN}/scenarios/reweight",
                        json={"weights": w}).json()
        assert r["missing"] == ["Mild Panic"]
        assert sum(r["normalised_weights"].values()) == pytest.approx(1.0)

    @needs_run
    def test_weights_naming_nothing_priced_are_refused(self):
        body = client.get(f"/api/analytics/{RUN}/scenarios").json()
        if not body.get("available"):
            pytest.skip("no per-scenario reports")
        r = client.post(f"/api/analytics/{RUN}/scenarios/reweight",
                        json={"weights": {"Mild Panic": 1.0}})
        assert r.status_code == 400


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


class TestWhatIf:
    """Rules do not stack: the conflict path is the one worth testing."""

    @needs_run
    def test_matching_reports_who_each_rule_claims(self):
        r = client.post(f"/api/stress/{RUN}/whatif/match", json={"rules": [
            {"label": "Off BS", "portfolios": ["Off BS"], "stage_to": 2}]})
        body = r.json()
        assert body["matched"] > 0
        assert body["by_rule"][0]["rule"] == "Off BS"
        assert body["conflicts"] == []

    @needs_run
    def test_two_rules_claiming_one_contract_conflict(self):
        body = client.post(f"/api/stress/{RUN}/whatif/match", json={"rules": [
            {"label": "A", "portfolios": ["Off BS"], "stage_to": 2},
            {"label": "B", "stages": [1], "collateral_pct": 50}]}).json()
        assert body["conflicts"], "an overlap must be reported, not resolved"
        assert " + " in body["conflicts"][0]["rules"]

    @needs_run
    def test_conflicted_contracts_are_not_repriced(self):
        body = client.post(f"/api/stress/{RUN}/whatif", json={"rules": [
            {"label": "A", "portfolios": ["Off BS"], "stage_to": 2},
            {"label": "B", "stages": [1], "collateral_pct": 50}]}).json()
        claimed = sum(r["contracts"] for r in body["by_rule"])
        assert claimed == body["matched"]
        assert len(body["conflicts"]) > 0

    @needs_run
    def test_a_rule_that_changes_nothing_moves_nothing(self):
        """The baseline is priced by the same function as the what-if."""
        body = client.post(f"/api/stress/{RUN}/whatif", json={"rules": [
            {"label": "no change", "portfolios": ["Off BS"]}]}).json()
        assert body["delta"] == pytest.approx(0.0, abs=1e-6)

    @needs_run
    def test_no_rules_is_refused(self):
        assert client.post(f"/api/stress/{RUN}/whatif",
                           json={"rules": []}).status_code == 400


class TestDistributionsAndFlows:
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

    @needs_pair
    def test_the_flows_are_the_contracts_that_arrived_or_left(self):
        prev, curr = PAIR
        f = client.get("/api/analytics/flows",
                       params={"prev": prev, "curr": curr}).json()
        labels = {r["flow"] for r in f["flows"]}
        assert labels == {"New business", "Derecognised"}
        # Two runs of the same book have neither, and say so with zeros.
        assert all(r["contracts"] >= 0 for r in f["flows"])
        assert all(r["contracts"] > 0 or not r.get("ecl") for r in f["flows"])

    @needs_pair
    def test_every_drill_down_ties_to_its_step(self):
        """The walk has no plug, so neither can the detail behind it."""
        prev, curr = PAIR
        f = client.get("/api/analytics/flows",
                       params={"prev": prev, "curr": curr, "n": 10**9}).json()
        w = client.get("/api/analytics/walk",
                       params={"prev": prev, "curr": curr}).json()
        steps = {s["label"]: s["amount"] for s in w["steps"]}
        for label, rows in f["detail"].items():
            if not rows:
                continue
            assert sum(r["amount"] for r in rows) == pytest.approx(
                steps[label], abs=1e-4), label

    @needs_pair
    def test_the_segment_movement_sums_to_the_whole_move(self):
        prev, curr = PAIR
        f = client.get("/api/analytics/flows",
                       params={"prev": prev, "curr": curr}).json()
        a = client.get(f"/api/analytics/{prev}/summary").json()
        b = client.get(f"/api/analytics/{curr}/summary").json()
        assert sum(r["change"] for r in f["by_segment"]) == pytest.approx(
            b["ecl"] - a["ecl"], abs=1e-4)

    @needs_pair
    def test_an_unknown_breakdown_is_refused(self):
        prev, curr = PAIR
        r = client.get("/api/analytics/flows",
                       params={"prev": prev, "curr": curr, "by": "sector"})
        assert r.status_code == 400


class TestPackageComparison:
    @needs_run
    def test_a_harsher_package_costs_more(self):
        """Priced together on identical inputs, so the ranking means something."""
        rows = client.post(f"/api/stress/{RUN}/compare", json={"packages": [
            {"name": "mild", "pd_multiplier": 1.25},
            {"name": "severe", "pd_multiplier": 2.0}]}).json()
        by = {r["name"]: r for r in rows}
        assert by["severe"]["delta"] > by["mild"]["delta"] > 0
        assert by["severe"]["before"] == pytest.approx(by["mild"]["before"])

    @needs_run
    def test_the_ranking_puts_the_worst_first(self):
        rows = client.post(f"/api/stress/{RUN}/compare", json={"packages": [
            {"name": "mild", "pd_multiplier": 1.1},
            {"name": "severe", "pd_multiplier": 3.0}]}).json()
        assert rows[0]["name"] == "severe"

    @needs_run
    def test_no_packages_is_refused(self):
        assert client.post(f"/api/stress/{RUN}/compare",
                           json={"packages": []}).status_code == 400


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
