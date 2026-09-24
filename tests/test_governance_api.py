"""The governance endpoints added for calculator versions and suppressions.

The API must not become a second implementation: these check that each
endpoint returns what the engine returns, and that the two refusals the engine
makes on purpose survive the HTTP layer.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


class TestCalculatorVersions:
    def test_the_registry_and_the_live_fingerprint_are_both_reported(self):
        r = client.get("/api/calculator/versions")
        assert r.status_code == 200
        body = r.json()
        assert set(body) >= {"root", "versions", "live_fingerprint", "for_run"}
        # The pair is the point: the registry says what a run would claim, the
        # fingerprint says what it would actually execute.
        assert len(body["live_fingerprint"]) == 32

    def test_an_empty_registry_is_not_an_error(self):
        body = client.get("/api/calculator/versions").json()
        assert isinstance(body["versions"], list)

    def test_nothing_to_compare_reads_as_unknown(self):
        """None, not False - unknown is not the same as drifted."""
        for_run = client.get("/api/calculator/versions").json()["for_run"]
        if not for_run.get("registered_hash"):
            assert for_run["matches_registered"] is None

    def test_a_bad_version_id_is_refused_with_400(self):
        r = client.post("/api/calculator/versions",
                        json={"id": "v1.0/../etc"})
        assert r.status_code == 400
        assert "letters, digits" in r.text

    def test_activating_an_unknown_version_is_404(self):
        r = client.post("/api/calculator/active/does-not-exist")
        assert r.status_code == 404


class TestCodeStatus:
    def test_it_always_answers(self):
        r = client.get("/api/code/status")
        assert r.status_code == 200
        assert set(r.json()) == {"sha", "dirty", "branch", "last_commit_at",
                                 "available"}


class TestSuppressions:
    def test_an_unknown_run_is_404(self):
        assert client.get("/api/suppressions/no_such_run").status_code == 404

    @pytest.mark.skipif(not client.get("/api/runs").json(),
                        reason="set IFRS9_RUNS_DIR to a folder holding runs")
    def test_listing_a_real_run(self):
        run_id = client.get("/api/runs").json()[0]["run_id"]
        body = client.get(f"/api/suppressions/{run_id}").json()
        assert set(body) == {"path", "entries", "active"}
        assert isinstance(body["entries"], list)

    @pytest.mark.skipif(not client.get("/api/runs").json(),
                        reason="set IFRS9_RUNS_DIR to a folder holding runs")
    def test_a_suppression_without_a_reason_is_refused(self):
        """The reason IS the audit trail, so the API must not accept a blank."""
        run_id = client.get("/api/runs").json()[0]["run_id"]
        r = client.post(f"/api/suppressions/{run_id}",
                        json={"validator_id": "INPUT_RS_coverage",
                              "reason": "", "approved_by": "priya"})
        assert r.status_code == 400
        assert "reason" in r.text

    @pytest.mark.skipif(not client.get("/api/runs").json(),
                        reason="set IFRS9_RUNS_DIR to a folder holding runs")
    def test_a_suppression_without_an_approver_is_refused(self):
        run_id = client.get("/api/runs").json()[0]["run_id"]
        r = client.post(f"/api/suppressions/{run_id}",
                        json={"validator_id": "INPUT_RS_coverage",
                              "reason": "accepted for Q1", "approved_by": ""})
        assert r.status_code == 400
        assert "approved_by" in r.text
