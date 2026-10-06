"""The R app's governance pages that had no Python counterpart.

    Approval queue   runs awaiting a checker and the decided history, with the
                     maker, the acting user and whether separation of duties
                     stops the maker approving; config versions awaiting
                     approval and their history
    Config versions  clone a version into a new draft; browse every file a
                     version froze; who created it and who is acting
    Suppressions     the PROJECT's suppressions (config/validation_
                     suppressions.yml), which the next pre-run check and run
                     apply, and the catalogue of validators that failed in
                     the last twenty runs
    Audit log        logs/etl_audit.jsonl, filtered by event, run and user,
                     one readable line per event
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ifrs9qdb.audit_log import event_label, event_summary, read_audit_log

from .. import settings

router = APIRouter(tags=["admin"])


def _records(df) -> list[dict]:
    if df is None or len(df) == 0:
        return []
    return df.astype(object).where(pd.notna(df), None).to_dict(orient="records")


# ------------------------------------------------------- approval queue ----
def _run_rows() -> pd.DataFrame:
    from ifrs9qdb.runs import list_runs
    return list_runs(settings.RUNS_DIR)


@router.get("/approval-queue/runs")
def queue_runs() -> dict:
    """Pending (awaiting a checker, or with no status file at all) and decided
    runs, each with the columns the R queue shows."""
    from ifrs9qdb.run_status import list_runs_decided, list_runs_pending_approval
    info = _run_rows()
    cols = ["run_id", "started_at", "duration_seconds", "user", "n_outputs",
            "n_validation_failures", "run_purpose", "portfolio_date"]
    info = info[cols] if len(info) else pd.DataFrame(columns=cols)
    pend = list_runs_pending_approval(settings.RUNS_DIR)
    dec = list_runs_decided(settings.RUNS_DIR)
    pend = pend.merge(info, on="run_id", how="left") if len(pend) else pend
    dec = dec.merge(info, on="run_id", how="left") if len(dec) else dec
    if len(dec):
        dec = dec.sort_values("decided_at", ascending=False)
    return {"pending": _records(pend), "decided": _records(dec)}


@router.get("/approval-queue/runs/{run_id}/context")
def run_context(run_id: str, acting_as: str | None = None) -> dict:
    """Who made the run, who is acting, and whether that stops them approving."""
    from ifrs9qdb.run_status import maker_for_run, normalise_status, read_run_status
    run = settings.RUNS_DIR / run_id
    if not run.is_dir():
        raise HTTPException(404, f"No run named {run_id!r}")
    maker = maker_for_run(run)
    checker = (acting_as or "").strip() or settings.current_user()
    enforce = settings.separation_enforced()
    same = bool(maker) and maker.strip().lower() == checker.lower()
    meta = read_run_status(run) or {}
    return {"run_id": run_id, "path": str(run), "maker": maker,
            "checker": checker, "enforced": enforce,
            "can_approve": not (enforce and same),
            "blocked_reason": (f"{maker} ran this pipeline; another user must "
                               "approve") if (enforce and same) else "",
            "status": normalise_status(meta.get("status")),
            "transitions": meta.get("transitions") or [],
            "overrides_applied": meta.get("overrides_applied") or {}}


@router.get("/approval-queue/versions")
def queue_versions() -> dict:
    """Config versions awaiting approval (pending_final), and the approved and
    archived ones with their decision trail -- newest decision first."""
    from ifrs9qdb.snapshots import list_snapshots, read_snapshot_metadata
    s = list_snapshots(settings.SNAPSHOTS_ROOT)
    pending = s[s["status"].isin(["pending_final", "pending"])] if len(s) else s
    hist = []
    for r in _records(s):
        if r.get("status") not in ("approved", "archived"):
            continue
        m = read_snapshot_metadata(r["label"], settings.SNAPSHOTS_ROOT) or {}
        trans = m.get("transitions") or []
        last = next((t for t in reversed(trans)
                     if t.get("to") == r["status"]), {}) if trans else {}
        hist.append({"label": r["label"], "status": r["status"],
                     "description": m.get("description") or "",
                     "requested_by": m.get("created_by"),
                     "requested_at": m.get("created_at"),
                     "decided_by": m.get("approved_by") or last.get("by"),
                     "decided_at": m.get("approved_at") or last.get("at"),
                     "decision_comment": m.get("approval_reason") or last.get("reason"),
                     "code_sha": m.get("code_sha_at_creation")})
    hist.sort(key=lambda d: str(d.get("decided_at") or ""), reverse=True)
    return {"pending": _records(pending), "decided": hist}


# ------------------------------------------------------- config versions ----
class CloneIn(BaseModel):
    new_label: str
    description: str
    created_by: str = ""


@router.post("/snapshots/{label}/clone")
def clone(label: str, body: CloneIn) -> dict:
    """Start a new draft from a version's content (the fix for a locked or
    rejected version)."""
    import re

    from ifrs9qdb.snapshots import clone_snapshot
    new = body.new_label.strip()
    if not new:
        raise HTTPException(400, "New label is required.")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", new):
        raise HTTPException(400, "Label must be [A-Za-z0-9._-]+")
    if not body.description.strip():
        raise HTTPException(400, "Description is required.")
    try:
        out = clone_snapshot(label, new, body.description.strip(),
                             created_by=body.created_by or settings.current_user(),
                             snapshots_root=settings.SNAPSHOTS_ROOT)
    except FileExistsError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "label": new, "path": str(out)}


@router.get("/snapshots/{label}/tree")
def snapshot_tree(label: str) -> dict:
    """Every file the version froze, under config/ and static/."""
    from ifrs9qdb.snapshots import read_snapshot_metadata, snapshot_dir
    meta = read_snapshot_metadata(label, settings.SNAPSHOTS_ROOT)
    if meta is None:
        raise HTTPException(404, f"No version named {label!r}")
    d = snapshot_dir(label, settings.SNAPSHOTS_ROOT)
    files = []
    for sub in ("config", "static"):
        base = d / sub
        if base.is_dir():
            for p in sorted(base.rglob("*")):
                if p.is_file():
                    files.append({"relpath": p.relative_to(d).as_posix(),
                                  "size": p.stat().st_size})
    return {"label": label, "dir": str(d), "meta": meta, "files": files}


@router.get("/snapshots/{label}/raw")
def snapshot_raw(label: str, relpath: str) -> dict:
    """One frozen file as text, read-only; refused over 200 KB (as R's)."""
    from ifrs9qdb.snapshots import snapshot_dir
    base = snapshot_dir(label, settings.SNAPSHOTS_ROOT).resolve()
    p = (base / relpath).resolve()
    if not str(p).startswith(str(base)) or not p.is_file():
        raise HTTPException(404, f"No file {relpath!r} in version {label!r}")
    size = p.stat().st_size
    if size > 200 * 1024:
        return {"path": str(p), "size": size, "too_large": True, "text": ""}
    return {"path": str(p), "size": size, "too_large": False,
            "text": p.read_text(encoding="utf-8", errors="replace")}


@router.get("/snapshots/{label}/promote-context")
def promote_context(label: str, acting_as: str | None = None) -> dict:
    """The allowed next statuses, the creator, the acting user, and whether
    separation of duties stops the creator approving."""
    from ifrs9qdb.snapshots import ALLOWED_TRANSITIONS, read_snapshot_metadata
    meta = read_snapshot_metadata(label, settings.SNAPSHOTS_ROOT)
    if meta is None:
        raise HTTPException(404, f"No version named {label!r}")
    cur = str(meta.get("status") or "draft")
    cur = "pending_final" if cur == "pending" else cur
    creator = meta.get("created_by") or ""
    me = (acting_as or "").strip() or settings.current_user()
    enforce = settings.separation_enforced()
    cant = enforce and creator and creator.strip().lower() == me.lower()
    return {"label": label, "status": cur, "meta": meta,
            "allowed": list(ALLOWED_TRANSITIONS.get(cur, ())),
            "created_by": creator, "acting_as": me, "enforced": enforce,
            "creator_cannot_approve": bool(cant)}


# ---------------------------------------------------------- suppressions ----
class ProjectSuppressionIn(BaseModel):
    validator_id: str
    reason: str
    approved_by: str = ""
    valid_until: str | None = None


class SuppressionRemoveIn(BaseModel):
    validator_id: str
    reason: str
    removed_by: str = ""


def _suppression_history(p) -> list[dict]:
    """Every entry in the file, in order, with where it stands today:
    active, expired, or removed (ended by remove_suppression, which keeps
    the entry and records who ended it and why)."""
    import pandas as pd
    import yaml
    from ifrs9qdb.validation import active_suppression_ids
    if not p.is_file():
        return []
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    out = []
    for e in raw.get("suppressions") or []:
        if not isinstance(e, dict):
            continue
        row = {k: ("" if e.get(k) is None else str(e.get(k)))
               for k in ("validator_id", "reason", "approved_by", "approved_at",
                         "valid_until", "removed_by", "removed_at",
                         "removal_reason")}
        one = pd.DataFrame([{k: row[k] for k in ("validator_id", "reason",
                                                 "approved_by", "approved_at",
                                                 "valid_until")}])
        row["status"] = ("removed" if row["removed_by"] else
                         "active" if active_suppression_ids(one) else "expired")
        out.append(row)
    return out


@router.get("/project-suppressions")
def project_suppressions() -> dict:
    """The project's suppressions -- what the NEXT pre-run check and run apply
    -- and the history of the file: every entry, active, expired or removed."""
    from ifrs9qdb.validation import active_suppression_ids, load_suppressions
    p = settings.SUPPRESSIONS_FILE
    table = load_suppressions(p)
    return {"path": str(p), "exists": p.is_file(), "entries": _records(table),
            "active": sorted(active_suppression_ids(table)),
            "history": _suppression_history(p)}


@router.post("/project-suppressions/remove")
def remove_project_suppression(body: SuppressionRemoveIn) -> dict:
    """End a standing suppression from today -- the entry is kept, with who
    ended it and why, and the audit log records a suppression_remove event.
    The finding then blocks again, and is asked about on each run."""
    from ifrs9qdb.validation import remove_suppression
    try:
        n = remove_suppression(settings.SUPPRESSIONS_FILE, body.validator_id,
                               body.reason,
                               (body.removed_by or "").strip()
                               or settings.current_user())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not n:
        raise HTTPException(404, f"No suppression of {body.validator_id!r} is in "
                                 "force.")
    return {**project_suppressions(), "removed": n}


@router.post("/project-suppressions")
def add_project_suppression(body: ProjectSuppressionIn) -> dict:
    from ifrs9qdb.validation import add_suppression
    if not body.validator_id.strip():
        raise HTTPException(400, "Validator ID is required.")
    if not body.reason.strip():
        raise HTTPException(400, "Reason is required (audit trail).")
    try:
        add_suppression(settings.SUPPRESSIONS_FILE, body.validator_id.strip(),
                        body.reason.strip(),
                        (body.approved_by or "").strip() or settings.current_user(),
                        body.valid_until or None)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return project_suppressions()


@router.get("/validator-catalog")
def validator_catalog(n_runs: int = 20) -> dict:
    """Every validator that FAILED in the most recent runs, once each, by
    stage, with where it was last seen -- the candidates to suppress."""
    from ifrs9qdb.runs import list_runs, read_run_validation
    runs = list_runs(settings.RUNS_DIR).head(n_runs)
    seen: dict[str, dict] = {}
    for r in runs.to_dict(orient="records"):
        v = read_run_validation(r["path"])
        if v is None or len(v) == 0 or "passed" not in v.columns:
            continue
        failed = v[v["passed"].astype(str).str.upper() != "TRUE"]
        for f in failed.to_dict(orient="records"):
            if f["id"] in seen:
                continue
            seen[f["id"]] = {"id": f["id"], "stage": f.get("stage", ""),
                             "severity": f.get("severity", ""),
                             "description": f.get("description", ""),
                             "last_seen_run": r["run_id"]}
    order = {"INPUT": 0, "TRANSFORM": 1, "DERIVED": 2, "READY": 3, "REPORT": 4}
    rows = sorted(seen.values(), key=lambda d: (order.get(d["stage"], 9), d["id"]))
    return {"n_runs": int(len(runs)), "validators": rows}


# ------------------------------------------------------------ audit log ----
@router.get("/audit-log")
def audit_log(event: str | None = None, run_id: str | None = None,
              user: str | None = None, limit: int = 2000) -> dict:
    """The project audit log, newest first, one readable line per event."""
    p = settings.AUDIT_LOG
    df = read_audit_log(p)
    events = sorted(x for x in df["event"].dropna().unique()) if len(df) else []
    runs = sorted((x for x in df["run_id"].dropna().astype(str).unique() if x),
                  reverse=True) if len(df) else []
    users = sorted(x for x in df["user"].dropna().astype(str).unique()) if len(df) else []
    if event:
        df = df[df["event"] == event]
    if run_id:
        df = df[df["run_id"].astype(str) == run_id]
    if user:
        df = df[df["user"].astype(str) == user]
    rows = []
    for r in df.to_dict(orient="records"):
        rows.append({"time": str(r.get("ts") or "").replace("T", " ")[:19],
                     "event": r.get("event"), "action": event_label(r.get("event")),
                     "user": r.get("user"),
                     "run": "" if pd.isna(r.get("run_id")) else str(r.get("run_id") or ""),
                     "details": event_summary(r)})
    rows.sort(key=lambda d: d["time"], reverse=True)
    return {"path": str(p), "exists": Path(p).is_file(), "n_events": int(len(rows)),
            "events": [{"id": e, "label": event_label(e)} for e in events],
            "runs": runs, "users": users, "rows": rows[:limit]}
