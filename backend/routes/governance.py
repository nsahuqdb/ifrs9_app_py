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


# ------------------------------------------- accepted findings -------------
def _suppressions_path(run_id: str) -> Path:
    """Where a run's accepted findings live.

    Inside the run's own frozen config when it has one, so reproducing a
    quarter uses the exceptions THAT quarter was signed with. Suppressions do
    not carry forward to a new snapshot.
    """
    run = _run(run_id)
    frozen = run / "config_used" / "config" / "validation_suppressions.yml"
    if frozen.parent.is_dir():
        return frozen
    return run / "validation_suppressions.yml"


class SuppressionIn(BaseModel):
    validator_id: str
    reason: str
    approved_by: str
    valid_until: str | None = None


@router.get("/suppressions/{run_id}")
def list_suppressions(run_id: str) -> dict:
    from ifrs9qdb.validation import active_suppression_ids, load_suppressions
    path = _suppressions_path(run_id)
    table = load_suppressions(path)
    return {
        "path": str(path),
        "entries": _records(table),
        "active": active_suppression_ids(table),
    }


@router.post("/suppressions/{run_id}")
def add_run_suppression(run_id: str, body: SuppressionIn) -> dict:
    """Accept a finding, with the reason and the approver recorded.

    Both are required by the engine. The endpoint does not supply a default
    approver: a name in an audit trail that nobody chose is worse than a
    refusal.
    """
    from ifrs9qdb.validation import add_suppression
    run = _run(run_id)
    try:
        path = add_suppression(_suppressions_path(run_id), body.validator_id,
                               body.reason, body.approved_by, body.valid_until,
                               audit=None)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        AuditLog(run / "audit.jsonl").record(
            "suppression_add", f"accepted {body.validator_id}",
            validator_id=body.validator_id, reason=body.reason,
            approved_by=body.approved_by, valid_until=body.valid_until or "")
    except Exception:
        pass
    return {"ok": True, "path": str(path)}


# ------------------------------------------- calculator versions -----------
PROJECT_ROOT = Path(os.environ.get("IFRS9_PROJECT_ROOT",
                                   Path(__file__).parent.parent.parent))


class CalculatorIn(BaseModel):
    id: str
    label: str = ""
    description: str = ""
    created_by: str = ""
    make_active: bool = True


@router.get("/calculator/versions")
def calculator_versions() -> dict:
    """The registry, plus what the CURRENTLY DEPLOYED code fingerprints to.

    The two together are the point: the registry says what a run would claim,
    the live fingerprint says what it would actually execute.
    """
    from ifrs9qdb.calculator_versions import (calculator_version_for_run,
                                              compute_code_fingerprint,
                                              list_calculator_versions)
    table = list_calculator_versions(PROJECT_ROOT)
    return {
        "root": str(PROJECT_ROOT),
        "versions": _records(table),
        "live_fingerprint": compute_code_fingerprint(),
        "for_run": calculator_version_for_run(root=PROJECT_ROOT),
    }


@router.post("/calculator/versions")
def register_calculator(body: CalculatorIn) -> dict:
    from ifrs9qdb.calculator_versions import register_calculator_version
    try:
        entry = register_calculator_version(
            body.id, body.label or None, body.description,
            body.created_by or None, body.make_active, root=PROJECT_ROOT)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "version": entry}


@router.post("/calculator/active/{version_id}")
def activate_calculator(version_id: str) -> dict:
    from ifrs9qdb.calculator_versions import set_active_calculator_version
    try:
        set_active_calculator_version(version_id, PROJECT_ROOT)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True, "active": version_id}


@router.get("/code/status")
def code_state() -> dict:
    """What code is deployed, as git sees it.

    ``dirty`` is the one that matters at close: a run produced from a modified
    working tree cannot be reproduced from its SHA.
    """
    from ifrs9qdb.code_version import code_status
    return code_status()


# ------------------------------------------------- maker-checker -----------
class DecisionIn(BaseModel):
    by: str
    reason: str


PROJECT_CONFIG = Path(os.environ.get("IFRS9_CONFIG",
                                     Path(__file__).parent.parent.parent
                                     / "config.yml"))


@router.get("/runstatus/queue")
def approval_queue_status() -> dict:
    """What is awaiting a checker, and what has been decided.

    A run with no status file is listed as ``unknown`` rather than hidden: it
    is the one most worth seeing, because something wrote a run and did not
    record that it needs approving.
    """
    from ifrs9qdb.run_status import (list_runs_decided,
                                     list_runs_pending_approval)
    return {"pending": _records(list_runs_pending_approval(RUNS_DIR)),
            "decided": _records(list_runs_decided(RUNS_DIR))}


@router.get("/runstatus/{run_id}")
def run_status(run_id: str) -> dict:
    from ifrs9qdb.run_status import maker_for_run, normalise_status, read_run_status
    run = _run(run_id)
    meta = read_run_status(run)
    if meta is None:
        return {"run_id": run_id, "status": "unknown", "meta": None,
                "maker": maker_for_run(run),
                "detail": ("This run has no reports/run_status.yml, so nothing "
                           "records that it is awaiting approval.")}
    return {"run_id": run_id, "status": normalise_status(meta.get("status")),
            "meta": meta, "maker": maker_for_run(run), "detail": ""}


def _decide(run_id: str, target: str, body: DecisionIn) -> dict:
    from ifrs9qdb.run_status import transition_run
    run = _run(run_id)
    try:
        meta = transition_run(run, target, body.by, body.reason,
                              config_path=PROJECT_CONFIG,
                              audit=AuditLog(run / "audit.jsonl"))
    except PermissionError as exc:
        # 403, not 400: this is a control refusing, not a malformed request.
        raise HTTPException(403, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "status": meta["status"], "meta": meta}


@router.post("/runstatus/{run_id}/approve")
def approve_status(run_id: str, body: DecisionIn) -> dict:
    return _decide(run_id, "approved", body)


@router.post("/runstatus/{run_id}/reject")
def reject_status(run_id: str, body: DecisionIn) -> dict:
    return _decide(run_id, "rejected", body)


# ------------------------------------------------- config snapshots --------
SNAPSHOTS_ROOT = Path(os.environ.get("IFRS9_SNAPSHOTS_DIR",
                                     PROJECT_ROOT / "config_snapshots"))


class SnapshotIn(BaseModel):
    label: str
    description: str = ""
    created_by: str = ""
    parent: str | None = None


class PromoteIn(BaseModel):
    status: str
    by: str
    reason: str


class EditIn(BaseModel):
    relpath: str
    text: str | None = None
    rows: list[dict] | None = None
    edited_by: str = ""


@router.get("/snapshots")
def snapshots() -> dict:
    from ifrs9qdb.snapshots import list_snapshots
    return {"root": str(SNAPSHOTS_ROOT),
            "snapshots": _records(list_snapshots(SNAPSHOTS_ROOT))}


@router.get("/snapshots/{label}")
def snapshot_detail(label: str) -> dict:
    from ifrs9qdb.snapshots import (editable_snapshot_files,
                                    read_snapshot_metadata)
    meta = read_snapshot_metadata(label, SNAPSHOTS_ROOT)
    if meta is None:
        raise HTTPException(404, f"No snapshot named {label!r}")
    return {"meta": meta,
            "editable": _records(editable_snapshot_files(label, SNAPSHOTS_ROOT))}


@router.get("/snapshots/{label}/file")
def snapshot_file(label: str, relpath: str) -> dict:
    """One file's content, as text for YAML and as rows for CSV.

    A CSV comes back with its comment header separate, because the static
    tables carry their provenance in leading `#` lines and a round trip that
    folds them into the data destroys them.
    """
    from ifrs9qdb.snapshots import read_static_csv_with_header, snapshot_dir
    base = snapshot_dir(label, SNAPSHOTS_ROOT)
    p = (base / relpath).resolve()
    if not str(p).startswith(str(base.resolve())) or not p.is_file():
        raise HTTPException(404, f"No file {relpath!r} in snapshot {label!r}")
    if p.suffix.lower() == ".csv":
        r = read_static_csv_with_header(p)
        return {"kind": "csv", "comment_header": r["comment_header"],
                "rows": _records(r["data"]),
                "columns": list(r["data"].columns)}
    return {"kind": "text", "text": p.read_text(encoding="utf-8")}


@router.post("/snapshots")
def create_snapshot_endpoint(body: SnapshotIn) -> dict:
    from ifrs9qdb.snapshots import create_snapshot
    try:
        out = create_snapshot(
            body.label, body.description, body.created_by or None,
            parent=body.parent or None,
            config_dir=PROJECT_ROOT / "config",
            static_dir=PROJECT_ROOT / "data-raw" / "static",
            run_config_path=PROJECT_CONFIG,
            snapshots_root=SNAPSHOTS_ROOT)
    except FileExistsError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "path": str(out)}


@router.post("/snapshots/{label}/promote")
def promote_snapshot_endpoint(label: str, body: PromoteIn) -> dict:
    from ifrs9qdb.snapshots import promote_snapshot
    run_audit = AuditLog(SNAPSHOTS_ROOT / "audit.jsonl")
    try:
        meta = promote_snapshot(label, body.status, body.by, body.reason,
                                snapshots_root=SNAPSHOTS_ROOT,
                                config_path=PROJECT_CONFIG, audit=run_audit)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "status": meta["status"], "meta": meta}


@router.post("/snapshots/{label}/edit")
def edit_snapshot(label: str, body: EditIn) -> dict:
    from ifrs9qdb.snapshots import save_snapshot_csv, save_snapshot_yaml
    audit = AuditLog(SNAPSHOTS_ROOT / "audit.jsonl")
    if body.rows is not None:
        r = save_snapshot_csv(label, body.relpath, pd.DataFrame(body.rows),
                              snapshots_root=SNAPSHOTS_ROOT,
                              edited_by=body.edited_by or None, audit=audit)
    else:
        r = save_snapshot_yaml(label, body.relpath, body.text or "",
                               snapshots_root=SNAPSHOTS_ROOT,
                               edited_by=body.edited_by or None, audit=audit)
    if not r.get("ok"):
        raise HTTPException(400, r.get("message", "the edit was refused"))
    return r


@router.get("/snapshots/{a}/diff/{b}")
def diff_snapshots_endpoint(a: str, b: str) -> dict:
    from ifrs9qdb.snapshots import diff_snapshots
    return diff_snapshots(a, b, SNAPSHOTS_ROOT)
