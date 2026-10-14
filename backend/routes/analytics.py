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

from .runs import _output_dir
from ifrs9qdb.analytics import (
    collateral_analysis, concentration, customer_lookup,
    customer_stage_migration, customer_view, data_quality,
    data_quality_detail, dpd_by_stage, ead_runoff, hhi,
    hhi_band, hhi_equivalent_n, lgd_floor_stats, lgd_vs_collateral,
    maturity_profile, mev_forecast_table, mev_weights_table, migration_summary,
    normalise, pd_profile, pd_term_structure, rating_migration, run_profile,
    scenario_comparison, scenario_ecl_from_outputs, scenario_severity,
    scenario_stage_split,
    scenario_weights, segment_matrix, stage2_trigger_overlap, stage2_triggers,
    stage3_drivers, staging_consistency, staging_distribution,
    top_contributors,
)
from ifrs9qdb.analytics import (  # noqa: F401  -- distributions
    collateral_bands, dpd_profile, exposure_bands, lgd_distribution,
    lorenz_curve, pd_by_rating, pd_distribution, vintage_profile,
)
from ifrs9qdb.analytics.model_view import config_used
from ifrs9qdb.stress import staging_threshold

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


def _threshold(run_id: str, given: float | None) -> float:
    """The Stage 2 DPD threshold to read a run's staging on: the one asked
    for, else the one the run froze with its config."""
    if given is not None:
        return given
    return staging_threshold(_output_dir(RUNS_DIR / run_id))


@router.get("/analytics/{run_id}/staging")
def staging(run_id: str, dpd_threshold: float | None = None) -> dict:
    d = _report(run_id)
    thr = _threshold(run_id, dpd_threshold)
    return {
        "dpd_threshold": thr,
        "distribution": _records(staging_distribution(d)),
        "triggers": _records(stage2_triggers(d, thr)),
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
def staging_detail(run_id: str, dpd_threshold: float | None = None) -> dict:
    """Staging read from the outcome: what triggered it, and where it
    disagrees with the rule that produced it -- the run's own rule unless a
    threshold is given."""
    d = _report(run_id)
    thr = _threshold(run_id, dpd_threshold)
    consistency = staging_consistency(d, thr)
    return {
        "dpd_threshold": thr,
        "dpd_by_stage": _records(dpd_by_stage(d)),
        "trigger_overlap": _records(stage2_trigger_overlap(d, thr)),
        "stage3_drivers": _records(stage3_drivers(d)),
        "consistency": {k: v for k, v in consistency.items() if k != "findings"},
        "findings": _records(consistency.get("findings")),
    }


@router.get("/analytics/migration")
def migration(prev: str, curr: str, top: int = 12) -> dict:
    """Who moved, on rating and on stage, between two runs.

    Counted as customers: rating and stage are customer attributes, so a
    contract count would count one customer once per facility.
    """
    a, b = _report(prev), _report(curr)
    return {
        "rating": _records(rating_migration(a, b, top=top, by_customer=True)),
        "rating_summary": _records(migration_summary(a, b)),
        "stage": _records(customer_stage_migration(a, b)),
    }


# ----------------------------------------------------------- bridge --------
def _jsonable(x):
    """Numbers, text and None only: numpy scalars and NaN are not JSON."""
    import math

    import numpy as np
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, pd.DataFrame):
        return _records(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        return None if math.isnan(float(x)) else float(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if x is pd.NA or x is pd.NaT:
        return None
    return x


def _bridge_stamp(run_id: str) -> tuple:
    p = report_path(run_id)
    od = _output_dir(RUNS_DIR / run_id)
    files = [p] + ([od / "StPD.csv"] if od is not None else [])
    return tuple((str(f), f.stat().st_mtime_ns) for f in files if f and f.is_file())


@lru_cache(maxsize=4)
def _bridge_cached(prev: str, curr: str, stamp: tuple) -> dict:
    from ifrs9qdb.analytics import ecl_bridge, load_bridge_run
    a = load_bridge_run(RUNS_DIR / prev, report_path(prev))
    b = load_bridge_run(RUNS_DIR / curr, report_path(curr))
    if not (a.ok and b.ok):
        raise HTTPException(400, a.reason or b.reason)
    return ecl_bridge(a, b)


def _bridge(prev: str, curr: str) -> dict:
    if report_path(prev) is None or report_path(curr) is None:
        raise HTTPException(404, "Both runs need an ECL report")
    return _bridge_cached(prev, curr, _bridge_stamp(prev) + _bridge_stamp(curr))


@router.get("/analytics/bridge")
def bridge(prev: str, curr: str, level: str = "book",
           members: list[str] = Query(default=[]), top: int = 200) -> dict:
    """Why the provision moved between two runs, for the whole book or for
    one or more customers, facilities, account types, segments, stages or
    ratings: each run's figures for the group, and the waterfall between
    them -- derecognised, new business, exposure, stage, rating, macro
    variables, model, LGD and collateral, overlay -- which sums exactly."""
    from ifrs9qdb.analytics import BRIDGE_LEVELS, bridge_view
    if level not in BRIDGE_LEVELS:
        raise HTTPException(400, f"level must be one of {', '.join(BRIDGE_LEVELS)}")
    if level != "book" and not members:
        raise HTTPException(400, "Choose at least one member of the level.")
    br = _bridge(prev, curr)
    v = bridge_view(br["rows"], level, members, top)
    return _jsonable({
        "level": level, "members": v["members"],
        "opening": v["opening"], "closing": v["closing"],
        "residual": v["residual"], "steps": v["steps"],
        "before": v["before"], "after": v["after"], "counts": v["counts"],
        "contracts": v["contracts"], "changes": br["changes"],
        "split": br["split"], "notes": br["notes"], "runs": br["runs"],
    })


@router.get("/analytics/bridge/members")
def bridge_members_route(prev: str, curr: str, level: str, q: str | None = None,
                         limit: int | None = None) -> list[dict]:
    """What can be chosen at a level, largest move first: every customer or
    facility unless ``limit`` says otherwise."""
    from ifrs9qdb.analytics import bridge_members
    return _records(bridge_members(_bridge(prev, curr)["rows"], level, q, limit))


@router.get("/analytics/bridge/by")
def bridge_by_route(prev: str, curr: str, level: str) -> list[dict]:
    """Every group of a level, each with its own waterfall in one row."""
    from ifrs9qdb.analytics import bridge_by
    try:
        return _records(bridge_by(_bridge(prev, curr)["rows"], level))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


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


@router.get("/analytics/{run_id}/scenarios/weights")
def scenario_weights_used(run_id: str) -> dict:
    """The scenario weights the run is priced with, both scales, as the engine
    resolves them from the run's frozen config -- not the config's rounded
    snapshot."""
    from ifrs9qdb.stress import run_scenario_weights
    return run_scenario_weights(_run_output(run_id))


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
    from ifrs9qdb.stress import run_scenario_weights
    used = run_scenario_weights(out_dir)
    return {
        "available": True,
        "severity": _records(scenario_severity(out_dir)),
        "weights": _records(scenario_weights(cu["config"])),
        # what the run is priced with, as the engine resolves them -- on an
        # automatic mode not the file's explicit block above
        "weights_used": ({"internal": used["internal"], "external": used["external"]}
                         if used.get("ok") else None),
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
def customers(run_id: str, ids: str = Query(...), spaces: bool = True) -> dict:
    """Look several customers up at once. Ids may be pasted any way;
    ``spaces=false`` reads them as a stress's scope does, so a name with
    spaces is one id."""
    got = customer_lookup(_report(run_id), ids, spaces=spaces)
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
