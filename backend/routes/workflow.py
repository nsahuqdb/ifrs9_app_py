"""The Run pipeline page, step by step -- the R app's mod_run_trigger.

    1. Input source   the configured folder, a data-drop folder, or an uploaded
                      zip; "Validate inputs" checks the bundle's structure and
                      previews every INPUT finding (advisory)
    2. Configuration  config version (the active approved one first), run type
                      (official needs an approved version), run purpose,
                      calculator version, portfolio date (filled from the
                      extract)
    3. Pre-run check  config, static and INPUT validators with the version's
                      suppressions -- an unsuppressed ERROR blocks the run --
                      and the readiness dry run: will every contract be priced?
    4. Phase 1        load, validate, transform; the run PAUSES with the
                      customer view for review
    5. Overrides      rating, stage (worsening only) and restructuring, each
                      with a reason
    6. Phase 2        overrides applied, curves, READY, pricing; the run lands
                      pending approval (official) or unofficial (terminal)

A paused run is held in this process, as the R app holds it in its session.
Long steps run in the background and are polled, so a browser never waits on
a request that outlives its timeout.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from ifrs9qdb.acquisition import (acquire_inputs_from_zip, list_data_drops,
                                  validate_input_directory)
from ifrs9qdb.audit_log import audit_event

from .. import settings
from .runs_detail import readiness_payload

router = APIRouter(tags=["workflow"])

_JOBS: dict[str, dict] = {}
_PAUSED: dict[str, dict] = {}
_LOCK = threading.Lock()

RUN_PURPOSES = {"official": ["regulatory"],
                "unofficial": ["non_regulatory", "impact"]}
PURPOSE_LABELS = {"regulatory": "Regulatory",
                  "non_regulatory": "Non-regulatory",
                  "impact": "Impact analysis"}


def _records(df) -> list[dict]:
    if df is None or len(df) == 0:
        return []
    return df.astype(object).where(pd.notna(df), None).to_dict(orient="records")


# ------------------------------------------------------------------ jobs ----
def _job(kind: str, work, **meta) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _LOCK:
        _JOBS[job_id] = {"kind": kind, "status": "running", "step": "starting",
                         "message": "Starting…", "result": None,
                         "started": time.time(), **meta}

    def progress(step, message):
        with _LOCK:
            _JOBS[job_id].update(step=step, message=message)

    def run():
        try:
            res = work(progress)
            with _LOCK:
                _JOBS[job_id].update(status="done", message="Finished", result=res)
        except Exception as exc:
            import traceback
            with _LOCK:
                _JOBS[job_id].update(status="failed",
                                     message=f"{type(exc).__name__}: {exc}",
                                     traceback=traceback.format_exc())

    threading.Thread(target=run, daemon=True).start()
    return job_id


@router.get("/workflow/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "No such job")
    out = {k: v for k, v in job.items() if k != "started"}
    out["seconds"] = round(time.time() - job["started"], 1)
    return {"job_id": job_id, **out}


# ----------------------------------------------------------- 1. sources ----
def _found_inputs(d: Path) -> int:
    """How many of the 12 extracts a folder holds, by name without extension
    (as the drop listing counts them: .xlsx one quarter, .xls the next)."""
    from ifrs9qdb.acquisition import expected_input_files
    if not d.is_dir():
        return 0
    stems = {Path(f).stem.lower() for f in expected_input_files()}
    found = {p.stem.lower() for p in d.iterdir()
             if p.is_file() and p.suffix.lower() in (".xlsx", ".xls", ".csv")}
    return len(stems & found)


@router.get("/workflow/sources")
def sources() -> dict:
    """The three input sources, as the R page offers them."""
    cfg = settings.input_dir()
    root = settings.data_drop_root()
    drops = list_data_drops(root) if root else None
    rows = []
    if drops is not None and len(drops):
        for r in drops.to_dict(orient="records"):
            r["modified"] = str(r.get("modified") or "")
            rows.append(r)
    return {"configured_dir": str(cfg), "configured_exists": cfg.is_dir(),
            "configured_found": _found_inputs(cfg),
            "drop_root": str(root) if root else "",
            "drop_root_exists": bool(root and root.is_dir()),
            "drops": rows, "upload_limit_mb": settings.max_upload_mb()}


@router.post("/workflow/upload-zip")
async def upload_zip(file: UploadFile = File(...)) -> dict:
    """Take a zip of the twelve extracts and unpack it into a fresh folder.

    A new folder per upload, never a reused one, so two uploads cannot mix.
    """
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "Upload a .zip file.")
    limit = settings.max_upload_mb() * 1024 * 1024
    dest = settings.UPLOAD_DIR / "zips"
    dest.mkdir(parents=True, exist_ok=True)
    zp = dest / f"{datetime.now():%Y%m%d_%H%M%S}_{Path(file.filename).name}"
    size = 0
    with open(zp, "wb") as fh:
        while True:
            chunk = await file.read(1 << 20)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                fh.close()
                zp.unlink(missing_ok=True)
                raise HTTPException(
                    413, f"The zip is larger than the upload limit "
                         f"({settings.max_upload_mb()} MB). Raise "
                         "run.max_upload_size_mb in config.yml if you need more.")
            fh.write(chunk)
    try:
        res = acquire_inputs_from_zip(zp, dest_root=settings.UPLOAD_DIR / "extracted")
    except Exception as exc:
        raise HTTPException(400, f"Zip extract failed: {exc}") from exc
    res["size_mb"] = round(size / 1e6, 2)
    return res


class SourceIn(BaseModel):
    kind: str = "configured"          # configured | drop_folder | upload | folder
    path: str | None = None
    source_zip: str | None = None
    extracted_at: str | None = None
    version: str | None = None        # config version, or "__LIVE__"


def _resolve_source(body: SourceIn) -> tuple[Path, dict]:
    kind = body.kind or "configured"
    if kind == "configured":
        d = settings.input_dir()
        return d, {"kind": "configured", "details": {"path": str(d)}}
    if not body.path:
        raise HTTPException(400, "Pick a folder (or upload a zip) first.")
    d = Path(body.path)
    if kind == "drop_folder":
        return d, {"kind": "drop_folder",
                   "details": {"path": str(d), "drop_name": d.name}}
    if kind == "upload":
        return d, {"kind": "upload",
                   "details": {"path": str(d), "source_zip": body.source_zip or "",
                               "extracted_at": body.extracted_at or ""}}
    return d, {"kind": "folder", "details": {"path": str(d)}}


def _version_paths(label: str | None):
    """(config_dir, static_dir, snapshot meta) for a config version, or the
    live config when none is picked."""
    from ifrs9qdb.snapshots import read_snapshot_metadata, snapshot_paths
    if not label or label == "__LIVE__":
        return settings.config_dir_for_run(), settings.static_dir_for_run(), None
    meta = read_snapshot_metadata(label, settings.SNAPSHOTS_ROOT)
    if meta is None:
        raise HTTPException(404, f"No config version named {label!r}")
    sp = snapshot_paths(label, settings.SNAPSHOTS_ROOT)
    cfg = sp["config_dir"] if (Path(sp["config_dir"]) / "model.yml").is_file() \
        else settings.config_dir_for_run()
    st = sp["static_dir"] if Path(sp["static_dir"]).is_dir() \
        else settings.static_dir_for_run()
    return cfg, st, meta


# Paths a config version freezes (they resolve inside the version) versus
# runtime locations that belong to the project (they resolve against it).
_VERSION_PATH_KEYS = ("variable_dictionary", "models", "model_inputs",
                      "model_config", "validation_suppressions")
# Where a run executes on this machine, not what it computes: taken from the
# live project config.yml, as R's snapshot_run_paths() does.
_RUNTIME_PATH_KEYS = ("input_dir", "output_dir", "runs_dir", "data_drop_root",
                      "reference_outputs")


def _run_config_for(label: str | None) -> dict:
    """The config.yml a run under this version uses.

    R reads the version's own frozen config.yml (pre_run_check(snapshot=),
    run_etl(snapshot=)): it names the model and the gating policy the version
    was approved with. Its model paths are pointed at the version's frozen
    files and static_dir at its static/; the runtime locations -- inputs,
    drops, runs, output, reference outputs -- are the live project config's,
    as R's snapshot_run_paths() takes them. Any other relative path resolves
    against the project. The live config.yml when no version is picked or
    the version carries none.
    """
    import yaml
    live = settings.run_config()
    if not label or label == "__LIVE__":
        return live
    from ifrs9qdb.snapshots import snapshot_paths
    sp = snapshot_paths(label, settings.SNAPSHOTS_ROOT)
    f = Path(sp["config_dir"]) / "config.yml"
    if not f.is_file():
        return live
    try:
        rc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    except Exception:
        return live
    paths = rc.get("paths") if isinstance(rc.get("paths"), dict) else {}
    live_paths = live.get("paths") if isinstance(live, dict) and isinstance(
        live.get("paths"), dict) else {}
    fixed = {}
    for k, v in paths.items():
        if k in _RUNTIME_PATH_KEYS:
            continue
        if not isinstance(v, str) or not v or Path(v).expanduser().is_absolute():
            fixed[k] = v
        elif k in _VERSION_PATH_KEYS:
            fixed[k] = str(Path(sp["config_dir"]) / Path(v).name)
        else:
            fixed[k] = str(settings.PROJECT_ROOT / v)
    for k in _RUNTIME_PATH_KEYS:
        v = live_paths.get(k)
        if v is None:
            continue
        fixed[k] = (str(settings.PROJECT_ROOT / v) if isinstance(v, str) and v
                    and not Path(v).expanduser().is_absolute() else v)
    fixed["static_dir"] = str(sp["static_dir"])
    rc["paths"] = fixed
    return rc


def _not_suppressible() -> set[str]:
    """The checks a suppression cannot silence: a missing input or reference
    file, a duplicate key in the tables the run joins on, an implausible
    reporting date, an incomplete run block. The pipeline page offers to
    accept a blocking finding only when it can be accepted."""
    from ifrs9qdb.validation import PREFLIGHT_VALIDATORS, STAGE_VALIDATORS
    from ifrs9qdb.validation.readiness import (READY_STAGE_VALIDATORS,
                                               REPORT_STAGE_VALIDATORS)
    return {v.id for v in (STAGE_VALIDATORS + PREFLIGHT_VALIDATORS
                           + READY_STAGE_VALIDATORS + REPORT_STAGE_VALIDATORS)
            if not v.suppressible}


def _suppressions_for(cfg_dir) -> Path:
    if cfg_dir is not None and (Path(cfg_dir) / "validation_suppressions.yml").is_file():
        return Path(cfg_dir) / "validation_suppressions.yml"
    return settings.SUPPRESSIONS_FILE


@router.post("/workflow/validate-inputs")
def validate_inputs(body: SourceIn) -> dict:
    """R's "Validate inputs": the structural check (gates the pre-run check),
    then the data-quality preview -- every INPUT validator against the chosen
    version's static reference, advisory only."""
    from ifrs9qdb.prerun import pre_run_check
    d, source = _resolve_source(body)
    check = validate_input_directory(d)
    n_fail = int((check["status"] == "FAIL").sum())
    out = {"input_dir": str(d), "input_source": source,
           "structural": _records(check), "n_fail": n_fail,
           "n_pass": int((check["status"] == "PASS").sum()),
           "ok": n_fail == 0, "dq": None, "strip_log": {}, "extract_date": None}
    if d.is_dir():
        try:
            cfg, st, _ = _version_paths(body.version)
            pr = pre_run_check(d, static_dir=st, config_dir=cfg,
                               suppressions_path=_suppressions_for(cfg),
                               record=False, include_preflight=False)
            f = pr["results"]
            failed = f[~f["passed"].astype(bool)]
            out["dq"] = {"summary": pr["summary"], "findings": _records(failed)}
            out["strip_log"] = pr["strip_log"]
            out["extract_date"] = pr["extract_date"]
        except HTTPException:
            raise
        except Exception as exc:
            out["dq_error"] = f"{type(exc).__name__}: {exc}"
    return out


# ------------------------------------------------------ 2. configuration ----
@router.get("/workflow/versions")
def versions() -> dict:
    """Config versions newest first, the active one (latest approved) pinned
    to the top and preselected; the default config last -- or first when
    nothing is approved yet."""
    from ifrs9qdb.snapshots import list_snapshots
    s = list_snapshots(settings.SNAPSHOTS_ROOT)
    rows = _records(s)
    active = next((r["label"] for r in rows if r.get("status") == "approved"), None)
    for r in rows:
        r["active"] = r["label"] == active
    if active:
        rows = [r for r in rows if r["active"]] + [r for r in rows if not r["active"]]
    return {"versions": rows, "active": active,
            "default_pick": active or "__LIVE__"}


@router.get("/workflow/run-type-check")
def run_type_check(run_type: str = "unofficial", version: str = "__LIVE__") -> dict:
    """Whether this (run type, version) pair may start -- the R gate: an
    official run needs an APPROVED config version."""
    from ifrs9qdb.snapshots import read_snapshot_metadata
    purposes = RUN_PURPOSES.get(run_type, RUN_PURPOSES["unofficial"])
    base = {"purposes": [{"id": p, "label": PURPOSE_LABELS[p]} for p in purposes]}
    if run_type != "official":
        return {"ok": True, "reason": "", **base,
                "note": "Unofficial run — skips approval. Export is marked UNOFFICIAL."}
    if not version or version == "__LIVE__":
        return {"ok": False, **base,
                "reason": "Official runs require an approved version. Default "
                          "config has no approval status — pick an approved "
                          "version, or switch to Unofficial."}
    meta = read_snapshot_metadata(version, settings.SNAPSHOTS_ROOT)
    if meta is None:
        return {"ok": False, "reason": "Could not read version metadata.", **base}
    if meta.get("status") != "approved":
        return {"ok": False, **base,
                "reason": f"Official runs require an approved version. "
                          f"'{version}' is currently '{meta.get('status') or 'unknown'}'. "
                          "Promote it to approved first, or switch to Unofficial."}
    return {"ok": True, "reason": "", **base,
            "note": "Official run — subject to approval."}


@router.get("/workflow/calculators")
def calculators() -> dict:
    """Calculator versions, active first, and what each would execute."""
    from ifrs9qdb.calculator_versions import (calculator_version_for_run,
                                              list_calculator_versions)
    from ifrs9qdb.runs import archived_code_for
    cv = list_calculator_versions(settings.PROJECT_ROOT)
    rows = []
    for r in _records(cv.sort_values("active", ascending=False) if len(cv) else cv):
        rows.append({**r, "runs_archived_code":
                     archived_code_for(r["id"], settings.PROJECT_ROOT) is not None})
    active = calculator_version_for_run(root=settings.PROJECT_ROOT)
    return {"versions": rows, "active": active}


# ------------------------------------------------------ 3. pre-run check ----
class PreRunIn(BaseModel):
    input_dir: str
    version: str | None = "__LIVE__"
    run_type: str = "unofficial"


@router.post("/workflow/pre-run-check")
def pre_run(body: PreRunIn) -> dict:
    """Config + static + INPUT validators with the version's suppressions.
    An unsuppressed ERROR blocks the run; WARNs are to review."""
    from ifrs9qdb.prerun import pre_run_check
    d = Path(body.input_dir)
    if not d.is_dir():
        raise HTTPException(400, f"No input directory at {d}")
    cfg, st, _ = _version_paths(body.version)
    pr = pre_run_check(d, static_dir=st, config_dir=cfg,
                       run_config=_run_config_for(body.version),
                       base_dir=settings.PROJECT_ROOT,
                       suppressions_path=_suppressions_for(cfg))
    f = pr["results"]
    flagged = f[~f["passed"].astype(bool)].copy()
    flagged["suppressible"] = ~flagged["id"].isin(_not_suppressible())
    s = pr["summary"]
    if s["errors"]:
        pill = ("error", f"{s['errors']} ERROR — Run blocked")
    elif s["warnings"]:
        pill = ("warn", f"{s['warnings']} WARN — review then proceed")
    else:
        pill = ("pass", f"All {s['passed']} checks passed")
    # A finding accepted on the pipeline page goes into the project's
    # validation_suppressions.yml. That is the file this check, the readiness
    # dry run and the run itself all read for the default config -- but not
    # for a config version, which carries its own frozen copy.
    live = not body.version or body.version == "__LIVE__"
    return {"summary": s, "blocked": s["errors"] > 0, "pill": pill,
            "flagged": _records(flagged), "extract_date": pr["extract_date"],
            "strip_log": pr["strip_log"],
            "run_type": run_type_check(body.run_type, body.version or "__LIVE__"),
            "suppressions_file": str(_suppressions_for(cfg)),
            "accept_here": bool(live and cfg is not None)}


@router.post("/workflow/readiness")
def start_readiness(body: PreRunIn) -> dict:
    """The readiness dry run, in the background (it builds the LIC files):
    which contracts would get no ECL, which LIC would blank, which are priced
    from incomplete inputs."""
    from ifrs9qdb.prerun import pre_run_readiness
    d = Path(body.input_dir)
    if not d.is_dir():
        raise HTTPException(400, f"No input directory at {d}")
    cfg, st, _ = _version_paths(body.version)

    def work(progress):
        r = pre_run_readiness(d, static_dir=st, config_dir=cfg, progress=progress)
        payload = (readiness_payload(r["contracts"], r["funnel"], r["markdown"])
                   if r.get("contracts") is not None else {"exists": False})
        v = r.get("validation")
        ready = []
        if v is not None and len(v):
            vv = v[(v["stage"] == "READY")
                   & (v["passed"].astype(str).str.upper() != "TRUE")].copy()
            vv["suppressible"] = ~vv["id"].isin(_not_suppressible())
            cols = [c for c in ("id", "severity", "effective_severity",
                                "context", "description", "message",
                                "suppressed", "suppressible") if c in vv.columns]
            ready = _records(vv[cols])
        return {"ok": r["ok"], "error": r["error"], "readiness": payload,
                "ready_findings": ready,
                "steps": r.get("steps") or []}

    return {"job_id": _job("readiness", work)}


# ------------------------------------------------------------ 4. phase 1 ----
class StartIn(BaseModel):
    input_dir: str
    input_source: dict | None = None
    version: str | None = "__LIVE__"
    run_type: str = "unofficial"
    run_purpose: str | None = None
    portfolio_date: str | None = None
    calculator_version: str | None = None
    user: str | None = None


@router.post("/workflow/start")
def start(body: StartIn) -> dict:
    """Phase 1 in the background; the run pauses for review when it ends."""
    from ifrs9qdb.etl.pipeline import run_etl_phase1
    d = Path(body.input_dir)
    if not d.is_dir():
        raise HTTPException(400, f"No input directory at {d}")
    gate = run_type_check(body.run_type, body.version or "__LIVE__")
    if not gate["ok"]:
        raise HTTPException(400, "Cannot start an Official run: " + gate["reason"])
    purposes = RUN_PURPOSES.get(body.run_type, RUN_PURPOSES["unofficial"])
    purpose = body.run_purpose if body.run_purpose in purposes else purposes[0]
    cfg, st, meta = _version_paths(body.version)
    user = (body.user or "").strip() or settings.current_user()
    rc = _run_config_for(body.version)
    policy = str((rc.get("run") or {}).get("on_validation_error") or "warn") \
        if isinstance(rc, dict) else settings.on_validation_error()
    if policy not in ("stop", "warn", "ignore"):
        policy = "warn"

    def work(progress):
        state = run_etl_phase1(
            d, settings.RUNS_DIR, static_dir=st, config_dir=cfg,
            progress=progress, run_type=body.run_type, user=user,
            on_validation_error=policy,
            run_purpose=purpose, portfolio_date=body.portfolio_date,
            snapshot_meta=meta, calculator_version=body.calculator_version or None,
            input_source=body.input_source, run_config=rc,
            project_root=settings.PROJECT_ROOT)
        if state.done:
            return {"paused": False, "run_id": state.run_id,
                    "result": state.result.as_dict()}
        with _LOCK:
            _PAUSED[state.run_id] = {
                "state": state, "started": datetime.now().isoformat(timespec="seconds"),
                "user": user, "version": body.version or "__LIVE__",
                "calculator_version": body.calculator_version or "",
                "overrides": {"rating": [], "stage": [], "restructuring": []}}
        return {"paused": True, "run_id": state.run_id,
                **_pause_summary(state.run_id)}

    return {"job_id": _job("phase1", work)}


def _paused(run_id: str) -> dict:
    p = _PAUSED.get(run_id)
    if p is None:
        raise HTTPException(404, f"No paused run {run_id!r} (the backend may have "
                                 "restarted since it paused)")
    return p


def _pause_summary(run_id: str) -> dict:
    p = _paused(run_id)
    st = p["state"]
    cv = st.customer_view()
    v = st.result.validation or {}
    n_find = sum(1 for r in st.stage_results for i in r.issues if not i.passed)
    return {"run_id": run_id, "customers": int(len(cv)),
            "investments": 0 if st.inv_view is None else int(len(st.inv_view)),
            "findings": int(n_find), "validation": v, "steps": st.result.steps,
            "started": p["started"], "user": p["user"],
            "version": p["version"], "run_type": st.run_type,
            "run_purpose": st.run_purpose,
            "pending": {k: len(v_) for k, v_ in p["overrides"].items()}}


@router.get("/workflow/paused")
def paused_runs() -> list[dict]:
    return [_pause_summary(k) for k in list(_PAUSED)]


@router.get("/workflow/paused/{run_id}")
def paused_run(run_id: str) -> dict:
    return _pause_summary(run_id)


@router.get("/workflow/paused/{run_id}/customers")
def paused_customers(run_id: str, q: str | None = None, stage: str | None = None,
                     offset: int = 0, limit: int = Query(50, le=1000)) -> dict:
    """The customer view for review: customer id, name, calculated rating,
    stage, restructuring, watchlist, exposure and worst DPD."""
    cv = _paused(run_id)["state"].customer_view()
    if q:
        ql = q.strip().lower()
        m = cv["customer_id"].astype(str).str.lower().str.contains(ql, regex=False)
        if "customer_name" in cv.columns:
            m |= cv["customer_name"].astype(str).str.lower().str.contains(ql, regex=False)
        cv = cv[m]
    if stage:
        cv = cv[cv["stage_final"] == stage]
    cv = cv.sort_values("exposure_total", ascending=False)
    return {"total": int(len(cv)), "offset": offset,
            "rows": _records(cv.iloc[offset: offset + limit])}


def _rating_choices(state) -> list[str]:
    ms = (state.static or {}).get("master_rating_scale")
    if ms is None or len(ms) == 0:
        return []
    internal = ms[ms["rating_type"].astype(str) == "Internal"].copy()
    internal["hierarchy"] = pd.to_numeric(internal["hierarchy"], errors="coerce")
    return internal.sort_values("hierarchy")["rating"].astype(str).tolist()


def _stage_choices(current: str) -> list[str]:
    """Only a worsening transition: Stage 1 -> 2 or 3, Stage 2 -> 3."""
    return {"Stage 1": ["Stage 2", "Stage 3"], "Stage 2": ["Stage 3"]}.get(
        str(current or "Stage 1"), [])


def _restr_choices(current: str) -> list[str]:
    return ["Not Restructured"] if str(current) == "Restructured" else ["Restructured"]


@router.get("/workflow/paused/{run_id}/customer/{customer_id}")
def paused_customer(run_id: str, customer_id: str) -> dict:
    st = _paused(run_id)["state"]
    cv = st.customer_view()
    hit = cv[cv["customer_id"].astype(str) == str(customer_id)]
    if hit.empty:
        raise HTTPException(404, f"No customer {customer_id!r} in this run")
    row = _records(hit)[0]
    return {"customer": row,
            "choices": {"rating": _rating_choices(st),
                        "stage": _stage_choices(row.get("stage_final")),
                        "restructuring": _restr_choices(row.get("restructuring_final"))}}


class OverrideIn(BaseModel):
    customer_id: str
    rating: str | None = None
    stage: str | None = None
    restructuring: str | None = None
    reason: str
    by: str | None = None


@router.post("/workflow/paused/{run_id}/overrides")
def add_override(run_id: str, body: OverrideIn) -> dict:
    """Add an override to the run's pending list -- checked as the R editor
    checks it: a reason always, at least one value, a rating on the internal
    scale, a stage only ever worse, restructuring flipped."""
    p = _paused(run_id)
    st = p["state"]
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(400, "Reason is required for any override.")
    vals = {k: (getattr(body, k) or "").strip()
            for k in ("rating", "stage", "restructuring")}
    if not any(vals.values()):
        raise HTTPException(400, "Pick at least one value to override.")
    info = paused_customer(run_id, body.customer_id)
    row, ch = info["customer"], info["choices"]
    if vals["rating"] and vals["rating"] not in ch["rating"]:
        raise HTTPException(400, f"{vals['rating']!r} is not on the internal rating scale.")
    if vals["stage"] and vals["stage"] not in ch["stage"]:
        raise HTTPException(400, f"A {row.get('stage_final')} customer cannot be "
                                 f"moved to {vals['stage']}: only a worsening stage "
                                 "is allowed, and Stage 3 cannot be overridden.")
    if vals["restructuring"] and vals["restructuring"] not in ch["restructuring"]:
        raise HTTPException(400, "Restructuring can only be flipped from what the "
                                 "model calculated.")
    who = (body.by or "").strip() or settings.current_user()
    now = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    prior = {"rating": row.get("rating_final"), "stage": row.get("stage_final"),
             "restructuring": row.get("restructuring_final") or ""}
    with _LOCK:
        for kind, v in vals.items():
            if not v:
                continue
            buf = p["overrides"][kind]
            buf[:] = [o for o in buf if o["customer_id"] != str(body.customer_id)]
            buf.append({"customer_id": str(body.customer_id), "value": v,
                        "prior_value": prior[kind] or "", "reason": reason,
                        "created_by": who, "created_at": now})
    return pending_overrides(run_id)


@router.get("/workflow/paused/{run_id}/overrides")
def pending_overrides(run_id: str) -> dict:
    p = _paused(run_id)
    return {"overrides": p["overrides"],
            "counts": {k: len(v) for k, v in p["overrides"].items()}}


@router.delete("/workflow/paused/{run_id}/overrides/{kind}/{customer_id}")
def drop_override(run_id: str, kind: str, customer_id: str) -> dict:
    p = _paused(run_id)
    if kind not in p["overrides"]:
        raise HTTPException(404, f"No override kind {kind!r}")
    with _LOCK:
        p["overrides"][kind] = [o for o in p["overrides"][kind]
                                if o["customer_id"] != str(customer_id)]
    return pending_overrides(run_id)


@router.post("/workflow/paused/{run_id}/cancel")
def cancel(run_id: str) -> dict:
    """Abandon a paused run. Its partial folder is removed -- it holds no
    outputs -- and the audit log records that it was cancelled."""
    with _LOCK:
        p = _PAUSED.pop(run_id, None)
    if p is None:
        raise HTTPException(404, f"No paused run {run_id!r}")
    run_dir = p["state"].run_dir
    if run_dir.is_dir() and not (run_dir / "Output" / "FinalEclReport.csv").exists():
        shutil.rmtree(run_dir, ignore_errors=True)
    audit_event({"event": "run_cancelled", "run_id": run_id,
                 "user": settings.current_user()})
    return {"ok": True, "run_id": run_id}


# ------------------------------------------------------------ 6. phase 2 ----
def _run_archived(state, code_dir: Path, overrides: dict, progress) -> dict:
    """The whole run, produced by an archived calculator's own code in a
    separate interpreter (see archived_runner.py)."""
    shim = Path(tempfile.mkdtemp(prefix="ifrs9_calc_"))
    try:
        (shim / "ifrs9qdb").symlink_to(code_dir, target_is_directory=True)
    except OSError:
        shutil.copytree(code_dir, shim / "ifrs9qdb")
    shutil.rmtree(state.run_dir, ignore_errors=True)   # the archived run rewrites it
    args = {"input_dir": str(state.input_dir), "runs_dir": str(state.runs_dir),
            "kwargs": {
                "run_id": state.run_id,
                "static_dir": str(state.static_dir) if state.static_dir else None,
                "config_dir": str(state.config_dir) if state.config_dir else None,
                "run_type": state.run_type, "user": state.user,
                "on_validation_error": state.on_validation_error,
                "overrides": overrides, "run_purpose": state.run_purpose,
                "portfolio_date": state.portfolio_date,
                "snapshot_meta": state.snapshot_meta,
                "calculator_version": state.calculator_version,
                "input_source": state.input_source,
                "run_config": state.run_config,
                "project_root": str(state.project_root)}}
    a, r = shim / "args.json", shim / "result.json"
    a.write_text(json.dumps(args, default=str), encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(shim) + os.pathsep + env.get("PYTHONPATH", "")
    env["IFRS9_AUDIT_LOG"] = str(settings.AUDIT_LOG)
    progress("archived", f"Running calculator {state.calculator_version} "
                         "(archived code)…")
    runner = Path(__file__).resolve().parent.parent / "archived_runner.py"
    subprocess.run([sys.executable, str(runner), str(a), str(r)], env=env,
                   cwd=str(shim), timeout=3600, check=False)
    try:
        out = json.loads(r.read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(shim, ignore_errors=True)
    out["archived_code"] = str(code_dir)
    return out


@router.post("/workflow/paused/{run_id}/continue")
def continue_run(run_id: str) -> dict:
    """Phase 2 with the pending overrides, in the background."""
    from ifrs9qdb.calculator_versions import (calculator_version_for_run,
                                              compute_code_fingerprint)
    from ifrs9qdb.etl.pipeline import run_etl_phase2
    from ifrs9qdb.runs import archived_code_for, augment_manifest_run_metadata
    p = _paused(run_id)
    st = p["state"]
    overrides = {k: list(v) for k, v in p["overrides"].items()}

    def work(progress):
        st.progress = progress
        code_dir = archived_code_for(st.calculator_version, settings.PROJECT_ROOT)
        if code_dir is not None:
            res = _run_archived(st, code_dir, overrides, progress)
        else:
            res = run_etl_phase2(st, overrides=overrides).as_dict()
        with _LOCK:
            _PAUSED.pop(run_id, None)
        # Stamp the operator's metadata from the app layer, as the R app does,
        # so it is recorded whichever code produced the run -- and, for an
        # archived calculator, the fingerprint of the code that actually ran.
        rec = calculator_version_for_run(id=st.calculator_version or None,
                                         root=settings.PROJECT_ROOT,
                                         code_dir=code_dir)
        augment_manifest_run_metadata(st.run_dir, {
            "run_type": st.run_type, "run_purpose": st.run_purpose,
            "portfolio_date": st.portfolio_date,
            "config_version": (st.snapshot_meta or {}).get("label"),
            "calculator_version": rec.get("id") or st.calculator_version,
            "calculator_label": rec.get("label"),
            "calculator_code_hash": compute_code_fingerprint(code_dir)
            if code_dir else rec.get("code_hash"),
            "calculator_matches_registered": rec.get("matches_registered")})
        res["run_type"] = st.run_type
        res["archived"] = code_dir is not None
        res["overrides_applied"] = res.get("overrides_applied") or \
            {k: len(v) for k, v in overrides.items()}
        return res

    return {"job_id": _job("phase2", work, run_id=run_id)}
