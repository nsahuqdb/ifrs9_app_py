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
from ..settings import (CONFIG_DIR, OVERLAYS_FILE, PROJECT_CONFIG,  # noqa: E402
                        PROJECT_ROOT, RUNS_DIR, SNAPSHOTS_ROOT)


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
    from ifrs9qdb.reconcile import reconcile_report
    return reconcile_report(_run(run_id), _run(reference_id))


@router.get("/summary/{run_id}")
def output_summary(run_id: str) -> list[dict]:
    from ifrs9qdb.reconcile import summarise_output_dir
    return _records(summarise_output_dir(_run(run_id)))


class ExportIn(BaseModel):
    include_inputs: bool = False


@router.post("/export/{run_id}")
def export(run_id: str, req: ExportIn) -> dict:
    """Package a run for handover or archive -- only an approved or unofficial
    run, as the R app allows (a run awaiting its checker is not a deliverable)."""
    from ifrs9qdb.reconcile import build_export

    from .runs_detail import export_status
    run_dir = _run(run_id)
    gate = export_status(run_dir.name)
    if not gate["exportable"]:
        raise HTTPException(403, f"Export refused: run is in status "
                                 f"'{gate['status']}'. {gate['reason']}")
    dest = run_dir / f"{run_id}_export.zip"
    res = build_export(run_dir, dest, include_inputs=req.include_inputs)
    AuditLog(run_dir / "audit.jsonl").record(
        "export", f"packaged {res['files']} files", zip=res["zip"])
    return res


@router.get("/export/{run_id}/download")
def export_download(run_id: str):
    """Hand the packaged zip back over HTTP.

    The app usually runs on a server, where telling somebody the path to a
    file on that server is not a handover.
    """
    from fastapi.responses import FileResponse

    from .runs_detail import export_status
    run_dir = _run(run_id)
    if not export_status(run_dir.name)["exportable"]:
        raise HTTPException(403, "Export refused for this run's status.")
    dest = run_dir / f"{run_id}_export.zip"
    if not dest.is_file():
        raise HTTPException(404, "Package the run first.")
    return FileResponse(dest, media_type="application/zip",
                        filename=dest.name)


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

    from ..settings import STATIC_DIR, config_dir_for_run, static_dir_for_run
    # R's manager refuses a version with no description: it is the audit trail.
    if not body.description.strip():
        raise HTTPException(400, "A description is required (audit trail).")
    try:
        out = create_snapshot(
            body.label, body.description, body.created_by or None,
            parent=body.parent or None,
            config_dir=config_dir_for_run() or CONFIG_DIR,
            static_dir=static_dir_for_run() or STATIC_DIR,
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


# ------------------------------------------------- overlay bundles ---------


class RuleIn(BaseModel):
    method: str
    level: str
    target: str | None = None
    value: float = 0.0
    comment: str = ""


class BundleIn(BaseModel):
    id: str
    name: str = ""
    owner: str = ""
    approval_ref: str = ""
    effective_date: str = ""
    expiry: str = ""
    rules: list[RuleIn] = []
    # R's save of an id that already exists asks: replace its rules, or
    # append the builder's to them. "new" refuses to overwrite.
    mode: str = "replace"
    by: str = ""


class StatusIn(BaseModel):
    status: str
    by: str
    reason: str


def _bundle_dict(body: BundleIn, existing: dict | None = None) -> dict:
    """The bundle as saved -- ALWAYS back to draft, as the R app saves it.

    An edited overlay is a new proposal: it cannot keep an approval given to
    different rules. The transition says whether it was created or edited.
    """
    from datetime import datetime as _dt

    from ..settings import current_user
    out = dict(existing or {})
    out.update({k: v for k, v in body.model_dump().items()
                if k not in ("rules", "mode", "by")})
    rules = [r.model_dump() for r in body.rules]
    if existing is not None and body.mode == "append":
        rules = list(existing.get("rules") or []) + rules
    out["rules"] = rules
    was = (existing or {}).get("status")
    out["status"] = "draft"
    out.setdefault("created_at", _dt.now().strftime("%Y-%m-%d"))
    out["transitions"] = list((existing or {}).get("transitions") or []) + [{
        "to": "draft", "by": body.by or current_user(),
        "at": _dt.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S"),
        "reason": ("created" if existing is None else
                   "edited - re-approval required" if was == "approved"
                   else "edited")}]
    return out


@router.get("/overlay-bundles")
def overlay_bundles() -> dict:
    from ifrs9qdb.overlays import read_overlay_bundles
    return {"path": str(OVERLAYS_FILE),
            "bundles": read_overlay_bundles(OVERLAYS_FILE)}


@router.post("/overlay-bundles")
def save_overlay_bundle(body: BundleIn) -> dict:
    from ifrs9qdb.audit_log import audit_event
    from ifrs9qdb.overlays import get_overlay, upsert_overlay
    existing = get_overlay(body.id, OVERLAYS_FILE)
    if existing is not None and body.mode == "new":
        raise HTTPException(409, f"Overlay '{body.id}' already exists with "
                                 f"{len(existing.get('rules') or [])} rule(s). "
                                 "Replace it, or append these rules to it.")
    bundle = _bundle_dict(body, existing)
    try:
        upsert_overlay(bundle, OVERLAYS_FILE)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit_event({"event": "overlay_saved", "overlay_id": body.id,
                 "n_rules": len(bundle["rules"]), "mode": body.mode,
                 "status": "draft"})
    return {"ok": True, "bundle": bundle}


@router.delete("/overlay-bundles/{overlay_id}")
def delete_overlay_bundle(overlay_id: str) -> dict:
    from ifrs9qdb.overlays import remove_overlay
    if not remove_overlay(overlay_id, OVERLAYS_FILE):
        raise HTTPException(404, f"No overlay named {overlay_id!r}")
    return {"ok": True}


@router.post("/overlay-bundles/{overlay_id}/status")
def set_bundle_status(overlay_id: str, body: StatusIn) -> dict:
    from ifrs9qdb.audit_log import audit_event
    from ifrs9qdb.overlays import get_overlay, set_overlay_status
    # R's buttons: submit a draft (or rejected) overlay; approve or reject a
    # pending one. A move outside that is refused rather than recorded.
    allowed = {"draft": ("pending",), "rejected": ("pending", "draft"),
               "pending": ("approved", "rejected", "draft"),
               "approved": ("draft",)}
    bundle = get_overlay(overlay_id, OVERLAYS_FILE)
    if bundle is None:
        raise HTTPException(404, f"No overlay named {overlay_id!r}")
    cur = bundle.get("status") or "draft"
    if body.status not in allowed.get(cur, ()):
        raise HTTPException(400, f"An overlay that is {cur} cannot move to "
                                 f"{body.status}. Allowed: "
                                 f"{', '.join(allowed.get(cur, ())) or 'none'}.")
    try:
        b = set_overlay_status(overlay_id, body.status, body.by, body.reason,
                               OVERLAYS_FILE)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit_event({"event": "overlay_status", "overlay_id": overlay_id,
                 "from_status": cur, "to_status": body.status,
                 "user": body.by, "reason": body.reason})
    return {"ok": True, "bundle": b}


@router.post("/overlay-bundles/{overlay_id}/preview/{run_id}")
def preview_bundle(overlay_id: str, run_id: str) -> dict:
    """What the overlay WOULD do to this run. Writes nothing."""
    from ifrs9qdb.overlays import get_overlay, preview_overlays as _preview
    bundle = get_overlay(overlay_id, OVERLAYS_FILE)
    if bundle is None:
        raise HTTPException(404, f"No overlay named {overlay_id!r}")
    p = _run(run_id) / "Output" / "FinalEclReport.csv"
    if not p.is_file():
        raise HTTPException(404, "This run has no ECL report to adjust")
    rep = normalise(pd.read_csv(p, low_memory=False))
    out = _preview(rep, bundle)
    if out.get("ok") and "summary" in out:
        out["summary"] = _records(out["summary"])
    return out


class PreviewRulesIn(BaseModel):
    id: str = "PREVIEW"
    rules: list[RuleIn] = []


@router.post("/overlay-rules/preview/{run_id}")
def preview_rules(run_id: str, body: PreviewRulesIn) -> dict:
    """What the builder's (unsaved) rules WOULD do to a run -- R's "Preview
    impact". Writes nothing."""
    from ifrs9qdb.overlays import preview_overlays as _preview
    from ifrs9qdb.overlays import validate_overlay_bundle
    bundle = {"id": body.id or "PREVIEW", "rules": [r.model_dump() for r in body.rules]}
    errs = validate_overlay_bundle(bundle)
    if errs:
        return {"ok": False, "errors": errs, "contracts": []}
    p = _run(run_id) / "Output" / "FinalEclReport.csv"
    if not p.is_file():
        raise HTTPException(404, "This run has no ECL report to adjust")
    out = _preview(normalise(pd.read_csv(p, low_memory=False)), bundle)
    if out.get("ok") and "summary" in out:
        out["summary"] = _records(out["summary"])
    return out


@router.post("/overlay-bundles/{overlay_id}/apply/{run_id}")
def apply_bundle(overlay_id: str, run_id: str) -> dict:
    """Apply the overlay to the run, alongside what it already produced."""
    from ifrs9qdb.overlays import apply_overlay_to_run, get_overlay
    bundle = get_overlay(overlay_id, OVERLAYS_FILE)
    if bundle is None:
        raise HTTPException(404, f"No overlay named {overlay_id!r}")
    run = _run(run_id)
    try:
        res = apply_overlay_to_run(run, bundle)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    if not res.get("ok"):
        return res
    res["audit"] = _records(res["audit"])
    try:
        AuditLog(run / "audit.jsonl").record(
            "overlay_applied", f"{overlay_id} applied",
            overlay_id=overlay_id, totals=res["totals"])
    except Exception:
        pass
    from ifrs9qdb.audit_log import audit_event
    audit_event({"event": "overlay_applied", "run_id": run_id,
                 "overlay_id": overlay_id, "status": res.get("status"),
                 "model": res["totals"]["model"],
                 "overlay": res["totals"]["overlay"],
                 "final": res["totals"]["final"]})
    return res


@router.get("/overlay-bundles/applied/{run_id}")
def applied_overlays(run_id: str) -> dict:
    from ifrs9qdb.overlays import list_applied_overlays
    return {"applied": _records(list_applied_overlays(_run(run_id)))}


@router.delete("/overlay-bundles/applied/{run_id}/{overlay_id}")
def remove_applied(run_id: str, overlay_id: str) -> dict:
    """Remove an overlay's outputs. The model report is untouched."""
    from ifrs9qdb.audit_log import audit_event
    from ifrs9qdb.overlays import remove_applied_overlay
    res = remove_applied_overlay(_run(run_id), overlay_id)
    if res.get("ok"):
        audit_event({"event": "overlay_removed", "run_id": run_id,
                     "overlay_id": overlay_id,
                     "removed": ", ".join(res.get("removed") or [])})
    return res
