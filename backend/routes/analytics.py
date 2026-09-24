"""Analytics endpoints.

Each one loads a run's report and calls the analytics package. No calculation
here: whatever the screen shows can be reproduced from a script with the same
functions.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from .runs import _output_dir
from ifrs9qdb.analytics import (
    concentration, customer_view, data_quality, ecl_walk, hhi, hhi_band,
    hhi_equivalent_n, maturity_profile, normalise, run_profile,
    stage2_triggers, staging_distribution, top_contributors,
)

router = APIRouter(tags=["analytics"])
RUNS_DIR = Path(os.environ.get("IFRS9_RUNS_DIR", "runs"))


def _report(run_id: str) -> pd.DataFrame:
    od = _output_dir(RUNS_DIR / run_id)
    path = (od / "FinalEclReport.csv") if od else Path("/nonexistent")
    if not path.is_file():
        raise HTTPException(404, f"No ECL report for run {run_id!r}")
    return normalise(pd.read_csv(path, low_memory=False))


def _records(df: pd.DataFrame) -> list[dict]:
    """JSON-safe records: NaN is not valid JSON, so it becomes null."""
    if df is None or len(df) == 0:
        return []
    return df.replace({float("nan"): None}).to_dict(orient="records")


@router.get("/analytics/{run_id}/summary")
def summary(run_id: str) -> dict:
    d = _report(run_id)
    exposure = float(d["exposure"].sum())
    ecl = float(d["ecl"].sum())
    cv = customer_view(d)
    h = hhi(d, "customer")
    return {
        "run_id": run_id,
        "contracts": int(len(d)),
        "customers": int(len(cv)),
        "exposure": exposure,
        "ecl": ecl,
        "coverage": 100 * ecl / exposure if exposure else None,
        "hhi": None if h != h else h,
        "hhi_band": hhi_band(h)["band"],
        "equivalent_customers": None if h != h else round(hhi_equivalent_n(h)),
        "stages": _records(staging_distribution(d)),
    }


@router.get("/analytics/{run_id}/portfolio")
def by_portfolio(run_id: str, by: str = Query("portfolio")) -> list[dict]:
    if by not in ("portfolio", "stage", "rating", "account_type"):
        raise HTTPException(400, "by must be portfolio, stage, rating or account_type")
    return _records(run_profile(_report(run_id), by))


@router.get("/analytics/{run_id}/staging")
def staging(run_id: str, dpd_threshold: float = 60) -> dict:
    d = _report(run_id)
    return {
        "distribution": _records(staging_distribution(d)),
        "triggers": _records(stage2_triggers(d, dpd_threshold)),
    }


@router.get("/analytics/{run_id}/concentration")
def conc(run_id: str, level: str = "customer") -> dict:
    d = _report(run_id)
    h = hhi(d, "customer")
    return {
        "hhi": None if h != h else h,
        "band": hhi_band(h),
        "equivalent_customers": None if h != h else round(hhi_equivalent_n(h)),
        "shares": _records(concentration(d, level=level)),
        "top": _records(top_contributors(d, 25, level=level)),
    }


@router.get("/analytics/{run_id}/quality")
def quality(run_id: str) -> list[dict]:
    return _records(data_quality(_report(run_id)))


@router.get("/analytics/{run_id}/maturity")
def maturity(run_id: str) -> list[dict]:
    return _records(maturity_profile(_report(run_id)))


@router.get("/analytics/walk")
def walk(prev: str, curr: str) -> dict:
    """Movement between two runs. The steps sum exactly to the closing balance."""
    w = ecl_walk(_report(prev), _report(curr))
    if not w:
        raise HTTPException(400, "Both runs need an ECL report")
    return {
        "opening": w["opening"], "closing": w["closing"],
        "residual": w["residual"], "counts": w["counts"],
        "steps": _records(w["steps"]),
    }
