"""API tests.

The API must not become a second implementation. These check that it returns
what the engine returns, including the EY golden figure through the HTTP layer.
"""
import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_health_reports_the_engine_version():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["engine_version"]


def test_runs_endpoint_is_empty_without_a_runs_directory():
    r = client.get("/api/runs")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_unknown_run_is_a_404():
    assert client.get("/api/runs/does_not_exist").status_code == 404


def test_lgd_endpoint_shows_the_floor_binding():
    unsecured = client.post("/api/ecl/lgd",
                            json={"on_balance": 100, "collateral_net": 0}).json()
    secured = client.post("/api/ecl/lgd",
                          json={"on_balance": 100, "collateral_net": 80}).json()
    assert unsecured["lgd"] == pytest.approx(0.45)
    assert unsecured["on_floor"] is False
    assert secured["lgd"] == pytest.approx(0.225)
    assert secured["on_floor"] is True


def test_price_reproduces_the_ey_golden_through_the_api():
    """EY contract 11 must come back as LIC's figure, not merely a plausible one."""
    on_bal = 113420.69
    r = client.post("/api/ecl/price", json={
        "contract_id": "11", "stage": 2, "on_balance": on_bal,
        "collateral_net": on_bal * 0.359537576,
        "cum_pd": [0.0] + [0.0129397176 * i for i in range(1, 11)],
        "eir": 0.05, "months_remaining": 10, "payment_type": 4,
    })
    assert r.status_code == 200
    assert r.json()["ecl"] == pytest.approx(2298.318, abs=1e-3)


def test_price_returns_the_curve_it_used():
    r = client.post("/api/ecl/price", json={
        "on_balance": 1000, "cum_pd": [0.0, 0.1], "months_remaining": 5,
        "payment_type": 4,
    }).json()
    curve = r["ead_curve"]
    assert curve[0] == pytest.approx(1000.0)
    assert curve[-1] < curve[0]


def test_stage_three_follows_the_configured_method():
    body = {"stage": 3, "on_balance": 1000, "cum_pd": [0.0, 0.5],
            "months_remaining": 12}
    full = client.post("/api/ecl/price", json={**body}).json()
    zero = client.post("/api/ecl/price",
                       json={**body, "stage3_method": "zero"}).json()
    assert full["ecl"] == pytest.approx(1000.0)
    assert zero["ecl"] == 0.0


class TestRunDiscovery:
    """Finding no runs must explain itself, not just report nothing."""

    def test_a_missing_directory_says_so(self, tmp_path, monkeypatch):
        import backend.routes.runs as R
        monkeypatch.setattr(R, "RUNS_DIR", tmp_path / "nope")
        d = R.diagnose()
        assert d["exists"] is False
        assert "does not exist" in d["hint"]
        assert d["resolved_to"]

    def test_a_misnamed_output_folder_is_named(self, tmp_path, monkeypatch):
        import backend.routes.runs as R
        (tmp_path / "run_00001" / "Outputs").mkdir(parents=True)
        monkeypatch.setattr(R, "RUNS_DIR", tmp_path)
        d = R.diagnose()
        assert d["exists"] is True
        e = d["entries"][0]
        assert e["accepted"] is False
        assert "Outputs" in e["contains"]
        assert "one level higher" in d["hint"]

    def test_output_folder_case_does_not_matter(self, tmp_path, monkeypatch):
        """The R app, a zip round-trip and a manual copy disagree on case, and
        Linux cares where Windows does not."""
        import backend.routes.runs as R
        for name in ("Output", "output", "OUTPUT"):
            run = tmp_path / f"run_{name}"
            (run / name).mkdir(parents=True)
            (run / name / "FinalEclReport.csv").write_text("Contract Id\n")
        monkeypatch.setattr(R, "RUNS_DIR", tmp_path)
        assert len(R.list_runs()) == 3

    def test_csvs_directly_in_the_run_folder_are_accepted(self, tmp_path, monkeypatch):
        import backend.routes.runs as R
        run = tmp_path / "run_flat"
        run.mkdir()
        (run / "FinalEclReport.csv").write_text("Contract Id\n")
        monkeypatch.setattr(R, "RUNS_DIR", tmp_path)
        got = R.list_runs()
        assert len(got) == 1 and got[0]["has_report"]

    def test_a_run_without_a_report_is_reported_not_hidden(self, tmp_path, monkeypatch):
        import backend.routes.runs as R
        (tmp_path / "run_x" / "Output").mkdir(parents=True)
        (tmp_path / "run_x" / "Output" / "StPD.csv").write_text("a\n")
        monkeypatch.setattr(R, "RUNS_DIR", tmp_path)
        d = R.diagnose()
        e = d["entries"][0]
        assert e["accepted"] is True and e["has_report"] is False
        assert "FinalEclReport" in e["reason"]


class TestWhatThePagesShow:
    """Fields the interface shows beside a run, a user and an input folder."""

    def test_health_names_who_is_acting(self, monkeypatch):
        monkeypatch.setenv("IFRS9_USER", "checker7")
        assert client.get("/api/health").json()["user"] == "checker7"

    def test_a_run_carries_its_date_type_and_status(self, tmp_path, monkeypatch):
        import json

        import backend.routes.runs as R
        run = tmp_path / "run_00001"
        (run / "Output").mkdir(parents=True)
        (run / "Output" / "FinalEclReport.csv").write_text("Contract Id\n")
        (run / "reports").mkdir()
        (run / "reports" / "manifest.json").write_text(json.dumps({
            "run_metadata": {"portfolio_date": "2026-06-30", "run_type": "official"},
            "run": {"started_at": "2026-07-02T09:00:00"}}))
        (run / "reports" / "run_status.yml").write_text("status: pending_approval\n")
        monkeypatch.setattr(R, "RUNS_DIR", tmp_path)
        got = R.list_runs()[0]
        assert (got["portfolio_date"], got["run_type"], got["status"]) == \
            ("2026-06-30", "official", "pending_approval")

    def test_a_run_without_a_manifest_still_lists(self, tmp_path, monkeypatch):
        import backend.routes.runs as R
        (tmp_path / "run_x" / "Output").mkdir(parents=True)
        (tmp_path / "run_x" / "Output" / "FinalEclReport.csv").write_text("a\n")
        monkeypatch.setattr(R, "RUNS_DIR", tmp_path)
        got = R.list_runs()[0]
        assert got["portfolio_date"] is None and got["status"] is None

    def test_the_input_folder_counts_the_extracts_it_holds(self, tmp_path):
        from backend.routes.workflow import _found_inputs
        assert _found_inputs(tmp_path / "missing") == 0
        assert _found_inputs(tmp_path) == 0
        # the same extract as .xlsx one quarter and .xls the next counts once
        for f in ("AccountMaster.xlsx", "AccountMaster.xls", "Collateral.xlsx",
                  "notes.txt"):
            (tmp_path / f).write_text("x")
        assert _found_inputs(tmp_path) == 2

    def test_the_pre_run_check_says_what_can_be_accepted(self, tmp_path):
        """A missing file cannot be suppressed; the page must not offer to."""
        from backend.routes.workflow import _not_suppressible
        blocked = _not_suppressible()
        assert blocked, "some checks must be beyond suppression"
        r = client.post("/api/workflow/pre-run-check",
                        json={"input_dir": str(tmp_path), "version": "__LIVE__"})
        assert r.status_code == 200
        body = r.json()
        assert body["blocked"] is True
        assert "accept_here" in body and body["suppressions_file"]
        for f in body["flagged"]:
            assert f["suppressible"] == (f["id"] not in blocked)
