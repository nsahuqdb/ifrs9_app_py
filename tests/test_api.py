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
