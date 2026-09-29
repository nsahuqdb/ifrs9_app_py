"""Analytics endpoints.

Each one loads a run's report and calls the analytics package. No calculation
here: whatever the screen shows can be reproduced from a script with the same
functions.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .runs import _output_dir
from ifrs9qdb.analytics import (
    collateral_analysis, concentration, coverage_bridge, customer_lookup,
    customer_stage_migration, customer_view, data_quality,
    data_quality_detail, dpd_by_stage, ead_runoff, ecl_factor_attribution,
    ecl_walk, factor_attribution_diagnosis, factor_attribution_exact, hhi,
    hhi_band, hhi_equivalent_n, lgd_floor_stats, lgd_vs_collateral,
    maturity_profile, mev_forecast_table, mev_weights_table, migration_summary,
    normalise, pd_profile, pd_term_structure, rating_migration, run_profile,
    scenario_comparison, scenario_ecl_from_outputs, scenario_reweight,
    scenario_sensitivity, scenario_severity, scenario_stage_split,
    scenario_weights, segment_matrix, stage2_trigger_overlap, stage2_triggers,
    stage3_drivers, stage_movers, staging_consistency, staging_distribution,
    top_contributors,
)
from ifrs9qdb.analytics import (  # noqa: F401  -- distributions and flows
    collateral_bands, dpd_profile, ecl_walk_detail, exposure_bands,
    flow_profile, lgd_distribution, lorenz_curve, movement_by,
    pd_by_rating, pd_distribution, vintage_profile,
)
from ifrs9qdb.analytics.model_view import config_used

router = APIRouter(tags=["analytics"])
from ..settings import RUNS_DIR  # noqa: E402


def report_path(run_id: str) -> Path | None:
    """The report the analytics read -- the OVERLAID one when an overlay has
    been applied to the run (the first, by name), else the model report. The
    R app's analytics page reads it the same way, so the two show the same
    provision."""
    od = _output_dir(RUNS_DIR / run_id)
    if od is None:
        return None
    ov = sorted(od.glob("FinalEclReport_overlay_*.csv"))
    if ov:
        return ov[0]
    p = od / "FinalEclReport.csv"
    return p if p.is_file() else None


def _report(run_id: str) -> pd.DataFrame:
    path = report_path(run_id)
    if path is None or not path.is_file():
        raise HTTPException(404, f"No ECL report for run {run_id!r}")
    return normalise(pd.read_csv(path, low_memory=False))


@router.get("/analytics/{run_id}/source")
def report_source(run_id: str) -> dict:
    """Which report file the analytics pages are reading for this run."""
    p = report_path(run_id)
    return {"file": p.name if p else None,
            "overlay": bool(p and p.name.startswith("FinalEclReport_overlay_")),
            "overlay_id": (p.stem[len("FinalEclReport_overlay_"):]
                           if p and p.name.startswith("FinalEclReport_overlay_")
                           else None)}


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


# ------------------------------------------------------------- risk --------
@lru_cache(maxsize=8)
def _inputs(run_id: str):
    """The engine inputs a run priced with, or None when they are not there.

    Cached: reading the eighteen CSVs and building the PD and EAD curves takes
    a few seconds, and the risk screen asks for them on every widget change.
    """
    from ifrs9qdb.inputs import load_engine_inputs

    od = _output_dir(RUNS_DIR / run_id)
    if od is None:
        raise HTTPException(404, f"No run named {run_id!r}")
    got = load_engine_inputs(od)
    return got if got.ok else None


def _run_output(run_id: str) -> Path:
    od = _output_dir(RUNS_DIR / run_id)
    if od is None:
        raise HTTPException(404, f"No run named {run_id!r}")
    return od


@router.get("/analytics/{run_id}/risk")
def risk(run_id: str, by: str = Query("stage"),
         portfolio: str | None = None) -> dict:
    """The risk parameters behind the provision, rather than the provision."""
    if by not in ("stage", "portfolio", "rating", "account_type"):
        raise HTTPException(400, "by must be stage, portfolio, rating or account_type")
    d = _report(run_id)
    inputs = _inputs(run_id)
    return {
        "pd": _records(pd_profile(d, by)),
        "lgd_floor": _records(lgd_floor_stats(d)),
        "lgd_scatter": _records(lgd_vs_collateral(d)),
        "term_structure": _records(pd_term_structure(inputs, portfolio))
        if inputs else [],
        "ead_runoff": _records(ead_runoff(inputs)) if inputs else [],
    }


@router.get("/analytics/{run_id}/collateral")
def collateral(run_id: str) -> dict:
    """What the collateral tables hold, and what did not join.

    An orphan allocation prices the contract as unsecured without erroring,
    so the count matters more than the totals.
    """
    inputs = _inputs(run_id)
    if inputs is None:
        return {"available": False,
                "reason": "This run's engine inputs could not be read."}
    c = collateral_analysis(inputs)
    if not c:
        return {"available": False,
                "reason": "This run has no collateral tables in its Output."}
    return {"available": True, "by_type": _records(c.pop("by_type")), **c}


@router.get("/analytics/{run_id}/segments")
def segments(run_id: str, rows: str = Query("portfolio"),
             cols: str = Query("stage"), value: str = Query("ecl")) -> list[dict]:
    try:
        return _records(segment_matrix(_report(run_id), rows, cols, value))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ---------------------------------------------------------- staging --------
@router.get("/analytics/{run_id}/staging-detail")
def staging_detail(run_id: str, dpd_threshold: float = 60) -> dict:
    """Staging read from the outcome: what triggered it, and where it
    disagrees with the rule that produced it."""
    d = _report(run_id)
    consistency = staging_consistency(d, dpd_threshold)
    return {
        "dpd_by_stage": _records(dpd_by_stage(d)),
        "trigger_overlap": _records(stage2_trigger_overlap(d, dpd_threshold)),
        "stage3_drivers": _records(stage3_drivers(d)),
        "consistency": {k: v for k, v in consistency.items() if k != "findings"},
        "findings": _records(consistency.get("findings")),
    }


@router.get("/analytics/migration")
def migration(prev: str, curr: str, top: int = 12,
              by_customer: bool = True) -> dict:
    """Who moved, on rating and on stage, between two runs."""
    a, b = _report(prev), _report(curr)
    return {
        "rating": _records(rating_migration(a, b, top=top,
                                            by_customer=by_customer)),
        "rating_summary": _records(migration_summary(a, b)),
        "stage": _records(customer_stage_migration(a, b)),
        "movers": _records(stage_movers(a, b).head(200)),
    }


# ------------------------------------------------------ attribution --------
@router.get("/analytics/attribution")
def attribution(prev: str, curr: str, by: str = Query("portfolio"),
                exact: bool = False) -> dict:
    """Why the provision moved.

    ``exact`` reprices every contract through the engine, which takes a
    second or two on a full book; the default indicative split is instant.
    """
    a, b = _report(prev), _report(curr)
    try:
        bridge = coverage_bridge(a, b, by)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    out = {"indicative": _records(ecl_factor_attribution(a, b)),
           "bridge": _records(bridge)}
    if not exact:
        return out

    ia, ib = _inputs(prev), _inputs(curr)
    res = factor_attribution_exact(ia, a, ib, b) if ia and ib else {}
    if not res:
        out["exact"] = None
        out["exact_reason"] = (factor_attribution_diagnosis(ia, a, ib, b)
                               or "The exact attribution could not be built.")
        return out
    out["exact"] = {
        "effects": _records(res["effects"]),
        **{k: res[k] for k in ("covered", "uncovered", "opening", "closing",
                               "contracts", "residual")},
    }
    return out


# -------------------------------------------------------- scenarios --------
@router.get("/analytics/{run_id}/scenarios")
def scenarios(run_id: str) -> dict:
    """The five per-scenario runs read back, ordered by severity."""
    out_dir = _run_output(run_id)
    ecl = scenario_ecl_from_outputs(out_dir)
    if not ecl.get("ok"):
        return {"available": False, "reason": ecl.get("reason")}
    severity = scenario_severity(out_dir)
    return {
        "available": True,
        "weighted": ecl.get("weighted"),
        "files": ecl.get("files"),
        "unreadable": ecl.get("unreadable"),
        "comparison": _records(scenario_comparison(ecl["ecl"], severity)),
        "stage_split": _records(scenario_stage_split(out_dir)),
    }


class Reweight(BaseModel):
    weights: dict[str, float]
    shift: float = 0.10


@router.post("/analytics/{run_id}/scenarios/reweight")
def reweight(run_id: str, body: Reweight) -> dict:
    """What the provision would be under a different set of weights."""
    out_dir = _run_output(run_id)
    ecl = scenario_ecl_from_outputs(out_dir)
    if not ecl.get("ok"):
        raise HTTPException(400, ecl.get("reason", "No scenario reports"))
    got = scenario_reweight(ecl["ecl"], body.weights)
    if got is None:
        raise HTTPException(400, "None of those weights name a priced scenario")
    return {
        "total": got["total"],
        "normalised_weights": got["normalised_weights"],
        "missing": got["missing"],
        "booked": ecl.get("weighted"),
        "sensitivity": _records(
            scenario_sensitivity(ecl["ecl"], body.weights, body.shift)),
    }


# ------------------------------------------------------- the model ---------
@router.get("/analytics/{run_id}/model")
def model(run_id: str) -> dict:
    """What the run froze: its scenarios, weights and macro forecast."""
    out_dir = _run_output(run_id)
    cu = config_used(out_dir)
    if cu is None:
        return {"available": False,
                "reason": "This run has no frozen config (config_used), so "
                          "the assumptions behind it cannot be shown."}
    return {
        "available": True,
        "severity": _records(scenario_severity(out_dir)),
        "weights": _records(scenario_weights(cu["config"])),
        "mev_forecast": _records(mev_forecast_table(out_dir)),
        "mev_weights": _records(mev_weights_table(out_dir)),
    }


# ------------------------------------------------- quality and lookup ------
@router.get("/analytics/{run_id}/quality-detail")
def quality_detail(run_id: str, n: int = 200) -> dict:
    """The contracts behind each finding, largest exposure first."""
    return {k: _records(v)
            for k, v in data_quality_detail(_report(run_id), n).items()}


@router.get("/analytics/{run_id}/customers")
def customers(run_id: str, ids: str = Query(...)) -> dict:
    """Look several customers up at once. Ids may be pasted any way."""
    got = customer_lookup(_report(run_id), ids)
    if not got:
        raise HTTPException(400, "No customer ids were given")
    return {"found": _records(got["found"]), "missing": got["missing"]}


# ---------------------------------------------------- distributions -------
@router.get("/analytics/{run_id}/distributions")
def distributions(run_id: str) -> dict:
    """The shape of the book, one profile per question.

    Each of these is a histogram somebody asks for by name at a review, and
    each carries its own conserved total: every contract lands in exactly one
    band, so a band that is missing is zero rather than absent.
    """
    d = _report(run_id)
    return {
        "dpd": _records(dpd_profile(d)),
        "exposure": _records(exposure_bands(d)),
        "collateral": _records(collateral_bands(d)),
        "vintage": _records(vintage_profile(d)),
        "lgd": _records(lgd_distribution(d)),
        "pd": _records(pd_distribution(d)),
        "pd_by_rating": _records(pd_by_rating(d)),
        "lorenz": _records(lorenz_curve(d, level="customer")),
    }


@router.get("/analytics/flows")
def flows(prev: str, curr: str, by: str = Query("portfolio"),
          n: int = 25) -> dict:
    """Arrivals, departures, and the detail behind each step of the walk.

    The walk says the provision moved; this says which contracts carried the
    movement. Every drill-down sums back to its own step, which is asserted in
    the package's tests rather than hoped for.
    """
    if by not in ("portfolio", "stage", "rating", "account_type"):
        raise HTTPException(400, "by must be portfolio, stage, rating or account_type")
    a, b = _report(prev), _report(curr)
    detail = ecl_walk_detail(a, b, n=n)
    return {
        "flows": _records(flow_profile(a, b)),
        "by_segment": _records(movement_by(a, b, by)),
        "detail": {label: _records(frame) for label, frame in detail.items()},
    }


@router.post("/analytics/{run_id}/scenarios/rebuild")
def scenarios_rebuild(run_id: str) -> dict:
    """Price each scenario from the run's frozen config, one at a time.

    Only for a run that did not write its per-scenario reports. Where it did,
    ``/scenarios`` reads them and cannot disagree with the run; this rebuilds
    the PD chain instead, which is slower and is a reconstruction rather than
    a record.
    """
    from ifrs9qdb.inputs import load_engine_inputs
    from ifrs9qdb.stress import scenario_ecl_single_run

    out_dir = _run_output(run_id)
    inputs = load_engine_inputs(out_dir)
    r = scenario_ecl_single_run(inputs, _report(run_id), out_dir)
    if not r.get("ok"):
        raise HTTPException(400, r.get("reason", "Could not rebuild the curves."))
    severity = scenario_severity(out_dir)
    return {
        "rebuilt": True,
        "comparison": _records(scenario_comparison(r["ecl"], severity)),
        "note": "Rebuilt from the run's frozen config, not read from its "
                "outputs. No weighted total: the run weights its marginal PDs "
                "before the curves are built, not its finished provisions.",
    }
