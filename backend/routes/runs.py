"""Run discovery.

A run is a directory holding Output/ and config_used/. Nothing here writes;
listing and reading only.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["runs"])

from ..settings import RUNS_DIR


def _output_dir(run: Path) -> Path | None:
    """The run's Output folder, whatever it is called.

    Case varies between the R app, a zip round-trip and a manual copy, and
    Linux cares where Windows does not. Some people also keep the CSVs directly
    in the run folder, so that is accepted too rather than reporting no runs.
    """
    for name in ("Output", "output", "OUTPUT"):
        d = run / name
        if d.is_dir():
            return d
    if (run / "FinalEclReport.csv").is_file():
        return run
    return None


def _run_dirs() -> list[Path]:
    if not RUNS_DIR.is_dir():
        return []
    found = [p for p in RUNS_DIR.iterdir()
             if p.is_dir() and _output_dir(p) is not None]
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def _run_labels(p: Path) -> dict:
    """What a run picker shows beside the id: the portfolio date, the run type
    and the approval status, from the manifest and reports/run_status.yml.
    Blank when a run predates them."""
    import json
    import yaml
    out = {"portfolio_date": None, "run_type": None, "status": None,
           "started_at": None}
    try:
        m = json.loads((p / "reports" / "manifest.json").read_text(encoding="utf-8"))
        meta = m.get("run_metadata") or {}
        run = m.get("run") or {}
        out["portfolio_date"] = meta.get("portfolio_date") or m.get("reporting_date")
        out["run_type"] = meta.get("run_type")
        out["started_at"] = run.get("started_at") or m.get("created")
    except Exception:
        pass
    try:
        rs = yaml.safe_load((p / "reports" / "run_status.yml").read_text(
            encoding="utf-8")) or {}
        out["status"] = rs.get("status")
        out["run_type"] = out["run_type"] or rs.get("run_type")
    except Exception:
        pass
    return out


@router.get("/runs")
def list_runs() -> list[dict]:
    """Runs available to the app, newest first."""
    out = []
    for p in _run_dirs():
        od = _output_dir(p)
        out.append({
            "run_id": p.name,
            "path": str(p),
            "has_report": (od / "FinalEclReport.csv").is_file(),
            "scenarios": sorted(
                f.name.replace("FinalEclReport_scenario_", "")
                      .replace(".csv", "").replace("_", " ")
                for f in od.glob("FinalEclReport_scenario_*.csv")),
            "has_frozen_config": (p / "config_used").is_dir(),
            **_run_labels(p),
        })
    return out


@router.get("/runs/_diagnose")
def diagnose() -> dict:
    """Why no runs were found.

    Guessing at a path problem from the outside wastes more time than reporting
    what was actually looked at, so this says: the directory resolved, whether
    it exists, and for each sub-folder why it was or was not accepted.
    """
    resolved = RUNS_DIR.resolve() if RUNS_DIR.exists() else RUNS_DIR
    info = {
        "IFRS9_RUNS_DIR": os.environ.get("IFRS9_RUNS_DIR", "(not set)"),
        "resolved_to": str(resolved),
        "exists": RUNS_DIR.is_dir(),
        "working_directory": os.getcwd(),
        "entries": [],
    }
    if not RUNS_DIR.is_dir():
        info["hint"] = (
            "That directory does not exist. Set IFRS9_RUNS_DIR to the folder "
            "that CONTAINS your run_XXXXX folders, then restart the backend.")
        return info

    for p in sorted(RUNS_DIR.iterdir()):
        if not p.is_dir():
            continue
        od = _output_dir(p)
        entry = {"name": p.name, "accepted": od is not None}
        if od is None:
            entry["reason"] = "no Output folder and no FinalEclReport.csv"
            entry["contains"] = sorted(x.name for x in p.iterdir())[:8]
        else:
            entry["output_dir"] = od.name
            entry["has_report"] = (od / "FinalEclReport.csv").is_file()
            entry["csv_count"] = len(list(od.glob("*.csv")))
            if not entry["has_report"]:
                entry["reason"] = "Output folder has no FinalEclReport.csv"
                entry["contains"] = sorted(x.name for x in od.glob("*.csv"))[:8]
        info["entries"].append(entry)

    if not info["entries"]:
        info["hint"] = (
            f"{resolved} exists but has no sub-folders. Point IFRS9_RUNS_DIR at "
            "the folder CONTAINING run_00001 etc, not at a run itself.")
    elif not any(e["accepted"] for e in info["entries"]):
        info["hint"] = (
            "Sub-folders were found but none holds an Output folder. If you "
            "pointed at a single run, point one level higher.")
    return info


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    p = RUNS_DIR / run_id
    od = _output_dir(p)
    if od is None:
        raise HTTPException(404, f"No run named {run_id!r}")
    return {"run_id": run_id, "path": str(p),
            "outputs": sorted(f.name for f in od.glob("*.csv"))}
