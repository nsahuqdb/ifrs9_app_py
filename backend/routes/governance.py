"""Overlays, snapshots, audit log and approval."""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ifrs9qdb.analytics import normalise
from ifrs9qdb.governance import (AuditLog, approval_status, approve_run,
                           compare_snapshots, read_snapshot)
from ifrs9qdb.overlays import Overlay, apply_overlays, read_overlays, validate_overlays
from ifrs9qdb.validation import validate_run
from .runs import _output_dir

router = APIRouter(tags=["governance"])
RUNS_DIR = Path(os.environ.get("IFRS9_RUNS_DIR", "runs"))
CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


def _run(run_id: str) -> Path:
    od = _output_dir(RUNS_DIR / run_id)
    if od is None:
        raise HTTPException(404, f"No run named {run_id!r}")
    return od.parent if od.name.lower() == "output" else od


def _records(df):
    if df is None or len(df) == 0:
        return []
    return df.replace({float("nan"): None}).to_dict(orient="records")


# ------------------------------------------------------------- overlays ----
class OverlayIn(BaseModel):
    id: str
    type: str
    value: float
    level: str = "contract"
    rationale: str = ""
    approved_by: str = ""
    enabled: bool = True
    stage: list = []
    portfolio: list = []
    rating: list = []
    flag: list = []
    customer: list = []
    contract_id: list = []
    whole_book: bool = False


@router.get("/overlays")
def list_overlays() -> list[dict]:
    return [o.__dict__ for o in read_overlays(CONFIG_DIR / "overlays.yml")]


@router.post("/overlays/{run_id}/preview")
def preview_overlays(run_id: str, overlays: list[OverlayIn]) -> dict:
    """Apply overlays to a run WITHOUT writing anything.

    A management adjustment should be seen before it is committed, and the
    overlap check is worth running on its own.
    """
    run_dir = _run(run_id)
    p = (run_dir / "Output" / "FinalEclReport.csv")
    if not p.is_file():
        raise HTTPException(404, "This run has no ECL report to adjust")
    rep = normalise(pd.read_csv(p, low_memory=False))
    objs = [Overlay(**o.model_dump()) for o in overlays]

    errs = validate_overlays(objs)
    if errs:
        return {"ok": False, "errors": errs}

    res = apply_overlays(rep, objs)
    if not res.get("ok"):
        return res
    return {
        "ok": True,
        "ecl_model_total": res["ecl_model_total"],
        "overlay_total": res["overlay_total"],
        "ecl_final_total": res["ecl_final_total"],
        "contracts_touched": res["contracts_touched"],
        "audit": _records(res["audit"]),
    }


# ------------------------------------------------------------ snapshots ----
@router.get("/snapshot/{run_id}")
def snapshot(run_id: str) -> dict:
    s = read_snapshot(_run(run_id))
    if s is None:
        return {"exists": False,
                "note": "This run has no frozen configuration, so what "
                        "produced it cannot be established from the run alone."}
    return {"exists": True, **s}


@router.get("/snapshot/{run_a}/compare/{run_b}")
def compare(run_a: str, run_b: str) -> list[dict]:
    return _records(compare_snapshots(_run(run_a), _run(run_b)))


# ------------------------------------------------------------ audit log ----
@router.get("/audit/{run_id}")
def audit(run_id: str) -> list[dict]:
    return AuditLog(_run(run_id) / "audit.jsonl").entries()


# ------------------------------------------------------------- approval ----
class ApprovalIn(BaseModel):
    stage: str
    approver: str
    comment: str = ""


@router.get("/approval/{run_id}")
def approval(run_id: str) -> dict:
    return approval_status(_run(run_id))


@router.post("/approval/{run_id}")
def approve(run_id: str, req: ApprovalIn) -> dict:
    """Record a sign-off, refused while validation is failing."""
    run_dir = _run(run_id)
    passed = validate_run(run_dir).passed
    try:
        return approve_run(run_dir, req.stage, req.approver, req.comment,
                           validation_passed=passed)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/approval")
def queue() -> list[dict]:
    """Every run and where it stands, for the approval queue."""
    out = []
    if not RUNS_DIR.is_dir():
        return out
    for p in sorted(RUNS_DIR.iterdir(), reverse=True):
        if not p.is_dir() or _output_dir(p) is None:
            continue
        st = approval_status(p)
        out.append({"run_id": p.name, **st})
    return out


# -------------------------------------------------------- reconciliation ---
@router.get("/reconcile/{run_id}/against/{reference_id}")
def reconcile(run_id: str, reference_id: str) -> dict:
    """Compare a run against another, file by file and on the provision."""
    from ...reconcile import reconcile_report
    return reconcile_report(_run(run_id), _run(reference_id))


@router.get("/summary/{run_id}")
def output_summary(run_id: str) -> list[dict]:
    from ...reconcile import summarise_output_dir
    return _records(summarise_output_dir(_run(run_id)))


class ExportIn(BaseModel):
    include_inputs: bool = False


@router.post("/export/{run_id}")
def export(run_id: str, req: ExportIn) -> dict:
    """Package a run for handover or archive."""
    from ...reconcile import build_export
    run_dir = _run(run_id)
    dest = run_dir / f"{run_id}_export.zip"
    res = build_export(run_dir, dest, include_inputs=req.include_inputs)
    AuditLog(run_dir / "audit.jsonl").record(
        "export", f"packaged {res['files']} files", zip=res["zip"])
    return res
