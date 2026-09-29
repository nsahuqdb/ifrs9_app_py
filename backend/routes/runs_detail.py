"""One run, in detail: the R app's Runs page.

The runs table with its approval status and health, and for one run its
manifest, validation, readiness, overrides, reconciliation and output files --
with a paged, filterable preview of any output CSV -- and the export, which is
offered only for an approved or unofficial run, as in the R app.
"""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ifrs9qdb.runs import (list_run_outputs, list_runs, manifest_inputs,
                           manifest_summary, read_input_source,
                           read_run_manifest, read_run_overrides,
                           read_run_readiness, read_run_reconciliation,
                           read_run_validation)

from .. import settings

router = APIRouter(tags=["runs"])


def _records(df) -> list[dict]:
    if df is None or len(df) == 0:
        return []
    return df.astype(object).where(pd.notna(df), None).to_dict(orient="records")


def _clean(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def _run_path(run_id: str) -> Path:
    p = settings.RUNS_DIR / run_id
    if not p.is_dir() or ".." in run_id or "/" in run_id:
        raise HTTPException(404, f"No run named {run_id!r}")
    return p


@router.get("/runs-table")
def runs_table() -> dict:
    """Every run with its manifest, status and health -- R's list_runs(), with
    the counts the page's summary tiles show."""
    df = list_runs(settings.RUNS_DIR)
    st = df["status"].fillna("unknown") if len(df) else pd.Series(dtype=str)
    tiles = {
        "total": int(len(df)),
        "approved": int((st == "approved").sum()),
        "pending_checker": int(st.isin(["pending_checker", "pending_approval"]).sum()),
        "unofficial": int((st == "unofficial").sum()),
        "with_validation_fails": int((pd.to_numeric(df["n_validation_failures"],
                                                    errors="coerce") > 0).sum())
        if len(df) else 0,
    }
    root = settings.RUNS_DIR
    return {"runs_dir": str(root.resolve() if root.exists() else root),
            "exists": root.is_dir(), "tiles": tiles, "runs": _records(df)}


@router.get("/runs/{run_id}/manifest")
def run_manifest(run_id: str) -> dict:
    run = _run_path(run_id)
    m = read_run_manifest(run)
    if m is None:
        return {"exists": False}
    return {"exists": True, "summary": {k: _clean(v) for k, v in
                                        manifest_summary(m, run).items()},
            "snapshot": m.get("snapshot"),
            "inputs": _records(manifest_inputs(m)),
            "input_source": read_input_source(run),
            "messages": m.get("messages") or [
                f"{s.get('step')}: {s.get('detail', '')}" for s in m.get("steps") or []]}


@router.get("/runs/{run_id}/validation-table")
def run_validation(run_id: str) -> dict:
    """validation.csv with a display status: PASS, SUPPR, or the effective
    severity -- failures first, as the R page sorts them."""
    v = read_run_validation(_run_path(run_id))
    if v is None or len(v) == 0:
        return {"exists": False, "rows": [], "counts": {}}
    passed = v["passed"].astype(str).str.upper() == "TRUE"
    supp = v.get("suppressed", pd.Series(["FALSE"] * len(v))).astype(str) \
        .str.upper() == "TRUE"
    eff = v["effective_severity"] if "effective_severity" in v.columns \
        else v["severity"]
    status = eff.str.upper().where(~passed, "PASS").where(~(supp & ~passed), "SUPPR")
    out = pd.DataFrame({"status": status, "stage": v.get("stage", ""),
                        "id": v["id"], "context": v.get("context", ""),
                        "description": v.get("description", ""),
                        "message": v.get("message", ""),
                        "rationale": v.get("rationale", ""),
                        "remediation": v.get("remediation", "")})
    out = out.iloc[passed.argsort(kind="stable")]
    return {"exists": True, "rows": _records(out),
            "counts": {"checks": int(len(v)), "passed": int(passed.sum()),
                       "failed": int((~passed).sum()),
                       "errors": int((status == "ERROR").sum()),
                       "warnings": int((status == "WARN").sum()),
                       "info": int((status == "INFO").sum()),
                       "suppressed": int((status == "SUPPR").sum())}}


@router.get("/runs/{run_id}/readiness")
def run_readiness(run_id: str) -> dict:
    """reports/readiness.csv, its funnel and summary -- which contracts get no
    ECL, which LIC would blank, which were priced from incomplete inputs."""
    rd = read_run_readiness(_run_path(run_id))
    if not rd or rd.get("contracts") is None:
        return {"exists": False}
    return readiness_payload(rd["contracts"], rd.get("funnel"), rd.get("markdown"))


def readiness_payload(con: pd.DataFrame, funnel=None, markdown=None) -> dict:
    """Summary by outcome, the reasons behind it, the funnel and the flagged
    contracts -- from readiness.csv (Outcome, OnBalance, Reasons as
    space-separated codes)."""
    from ifrs9qdb.validation.readiness import (READINESS_REASONS,
                                               READINESS_REMEDIATION)
    ob = pd.to_numeric(con.get("OnBalance"), errors="coerce").fillna(0)
    outcome = con.get("Outcome", pd.Series([""] * len(con)))
    summary = {"contracts": int(len(con)), "exposure": float(ob.sum())}
    for o in ("No ECL", "Blank in LIC", "Priced - check", "Priced"):
        m = outcome == o
        summary[o] = {"contracts": int(m.sum()), "exposure": float(ob[m].sum())}
    reasons = []
    codes = con.get("Reasons", pd.Series([""] * len(con))).fillna("").astype(str)
    ex = pd.DataFrame({"code": codes.str.split(), "ob": ob}).explode("code")
    ex = ex[ex["code"].notna() & (ex["code"] != "")]
    if len(ex):
        g = ex.groupby("code").agg(contracts=("code", "size"),
                                   exposure=("ob", "sum")).reset_index()
        for _, r in g.iterrows():
            spec = READINESS_REASONS.get(r["code"])
            reasons.append({
                "code": r["code"],
                "check": spec[0] if spec else r["code"],
                "severity": spec[1] if spec else "",
                "outcome": spec[2] if spec else "",
                "text": spec[3] if spec else "",
                "fix": READINESS_REMEDIATION.get(r["code"], ""),
                "contracts": int(r["contracts"]), "exposure": float(r["exposure"])})
        rank = {"ERROR": 0, "WARN": 1, "INFO": 2}
        reasons.sort(key=lambda d: (rank.get(d["severity"], 3), -d["exposure"]))
    flagged = con[outcome != "Priced"]
    return {"exists": True, "summary": summary, "reasons": reasons,
            "funnel": _records(funnel),
            "flagged": _records(flagged.head(5000)),
            "n_flagged": int(len(flagged)),
            "markdown": markdown}


@router.get("/runs/{run_id}/overrides")
def run_overrides(run_id: str) -> dict:
    run = _run_path(run_id)
    if not (run / "overrides").is_dir():
        return {"exists": False, "files": []}
    return {"exists": True,
            "files": [{"file": k, "rows": _records(v) if v is not None else None,
                       "readable": v is not None}
                      for k, v in read_run_overrides(run).items()]}


@router.get("/runs/{run_id}/reconciliation")
def run_reconciliation(run_id: str) -> dict:
    return read_run_reconciliation(_run_path(run_id))


@router.get("/runs/{run_id}/outputs")
def run_outputs(run_id: str) -> dict:
    files = list_run_outputs(_run_path(run_id))
    return {"files": [{"file": p.name, "size_kb": round(p.stat().st_size / 1024, 1),
                       "path": str(p)} for p in files]}


@router.get("/runs/{run_id}/outputs/{name}")
def run_output_preview(run_id: str, name: str, offset: int = 0,
                       limit: int = Query(200, le=5000),
                       q: str | None = None, column: str | None = None) -> dict:
    """A page of one output CSV, optionally filtered -- on one column, or on
    any column containing ``q``. Identifier columns are compared as text, so
    a contract id finds its row exactly. Up to 20,000 rows are read, as the R
    preview does."""
    files = {p.name: p for p in list_run_outputs(_run_path(run_id))}
    p = files.get(name)
    if p is None:
        raise HTTPException(404, f"No output {name!r} in {run_id}")
    df = pd.read_csv(p, dtype=str, keep_default_na=False, nrows=20000)
    with open(p, "rb") as fh:
        n_lines = sum(chunk.count(b"\n") for chunk in iter(lambda: fh.read(1 << 20), b""))
    if q:
        ql = q.strip().lower()
        if column and column in df.columns:
            m = df[column].str.lower().str.contains(ql, regex=False)
        else:
            m = pd.Series(False, index=df.index)
            for c in df.columns:
                m |= df[c].str.lower().str.contains(ql, regex=False)
        df = df[m]
    total = int(len(df))
    page = df.iloc[offset: offset + limit]
    return {"file": name, "path": str(p),
            "size_kb": round(p.stat().st_size / 1024, 1),
            "lines": max(0, n_lines - 1), "truncated": n_lines - 1 > 20000,
            "columns": list(df.columns), "total": total, "offset": offset,
            "rows": page.to_dict(orient="records")}


class ExportIn(BaseModel):
    include_inputs: bool = True


def _status(run: Path) -> str:
    from ifrs9qdb.run_status import normalise_status, read_run_status
    s = read_run_status(run)
    return normalise_status(s.get("status")) if s else "unknown"


@router.get("/runs/{run_id}/export-status")
def export_status(run_id: str) -> dict:
    """Whether the run can be exported, and why not -- R's gate: approved or
    unofficial only."""
    st = _status(_run_path(run_id))
    ok = st in ("approved", "unofficial")
    why = {
        "pending_checker": "This run is awaiting checker approval. Export becomes "
                           "available after a checker approves the run on the "
                           "Approval queue.",
        "rejected": "This run was rejected. Rejected runs are not exportable.",
        "unknown": "This run has no recorded approval status (run_status.yml "
                   "missing or unparseable). Export is disabled.",
    }.get(st, f"Export is disabled in status '{st}'.")
    return {"status": st, "exportable": ok, "reason": "" if ok else why,
            "unofficial": st == "unofficial"}


@router.post("/runs/{run_id}/export")
def export_run(run_id: str, req: ExportIn) -> dict:
    """Build the run package -- refused unless approved or unofficial, even
    when called directly (defence in depth, as the R handler does)."""
    from ifrs9qdb.reconcile import build_export
    run = _run_path(run_id)
    gate = export_status(run_id)
    if not gate["exportable"]:
        raise HTTPException(403, f"Export refused: run is in status "
                                 f"'{gate['status']}'. {gate['reason']}")
    dest = run / f"ifrs9_run_{run_id}.zip"
    res = build_export(run, dest, include_inputs=req.include_inputs)
    res["download"] = f"/api/runs/{run_id}/export/download"
    return res


@router.get("/runs/{run_id}/export/download")
def export_download(run_id: str):
    run = _run_path(run_id)
    gate = export_status(run_id)
    if not gate["exportable"]:
        raise HTTPException(403, "Export refused for this run's status.")
    dest = run / f"ifrs9_run_{run_id}.zip"
    if not dest.is_file():
        raise HTTPException(404, "Build the package first.")
    return FileResponse(dest, media_type="application/zip", filename=dest.name)
