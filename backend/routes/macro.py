"""The macro store and the new-quarter config fill.

The store is a folder of vintages (ifrs9qdb.macro.MacroStore) under the
project's macro_store/; a refresh fetches every IMF dataset of the catalogue
for its countries -- falling back to the DataMapper, DBnomics or files when
the IMF cannot be reached -- and saves one new vintage. The new-quarter fill
reads a config (the live one or a snapshot's), proposes the forecasts,
history and scenario weights the store gives, and writes them into a DRAFT
snapshot for testing and approval. Nothing here reads or changes a run.
"""
from __future__ import annotations

import math
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from ifrs9qdb.macro import MacroStore, concepts, countries, datasets, import_file, refresh
from ifrs9qdb.macro.fetch import DEFAULT_SOURCES
from ifrs9qdb.macro.store import last_actual_guess
from ifrs9qdb.macro.quarter import apply as apply_quarter
from ifrs9qdb.macro.quarter import MODELS, propose

from ..settings import CONFIG_DIR, MACRO_STORE_DIR, PROJECT_ROOT, SNAPSHOTS_ROOT, STATIC_DIR

router = APIRouter(tags=["macro"])


def js(x):
    """JSON-safe: NaN and infinity become null, numpy becomes Python."""
    if isinstance(x, dict):
        return {str(k): js(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [js(v) for v in x]
    if isinstance(x, np.ndarray):
        return [js(v) for v in x.tolist()]
    if isinstance(x, pd.DataFrame):
        return [js(r) for r in x.to_dict(orient="records")]
    if isinstance(x, pd.Series):
        return js(x.to_dict())
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if x is pd.NA or x is pd.NaT:
        return None
    return x


def store() -> MacroStore:
    MACRO_STORE_DIR.mkdir(parents=True, exist_ok=True)
    return MacroStore(MACRO_STORE_DIR)


@router.get("/macro/status")
def status() -> dict:
    """The store's vintages, the latest one's fetch log, and every concept
    with the series it resolves to."""
    st = store()
    v = st.vintages()
    latest = st.latest()
    meta = st.meta(latest) if latest else {}
    return js({"store_dir": str(MACRO_STORE_DIR), "latest": latest,
               "vintages": v.iloc[::-1], "log": meta.get("log") or [],
               "created": meta.get("created"), "label": meta.get("label"),
               "concepts": st.resolve_concepts(latest, PROJECT_ROOT) if latest else []})


@router.get("/macro/catalogue")
def catalogue() -> dict:
    return js({"datasets": datasets(PROJECT_ROOT), "countries": countries(PROJECT_ROOT),
               "concepts": concepts(PROJECT_ROOT)})


class RefreshIn(BaseModel):
    groups: list[str] | None = None
    datasets: list[str] | None = None
    sources: list[str] = Field(default_factory=lambda: list(DEFAULT_SOURCES))
    fred_key: str | None = None
    label: str = ""
    all_datasets: bool = False


_JOBS: dict = {}


@router.post("/macro/refresh")
def do_refresh(body: RefreshIn) -> dict:
    """Start fetching one vintage in the background -- every dataset takes a
    few minutes -- and return the job to follow with GET /macro/refresh/{job}."""
    import threading
    import uuid
    job = uuid.uuid4().hex[:12]
    if any(v["status"] == "running" for v in _JOBS.values()):
        raise HTTPException(409, "A refresh is already running.")
    import datetime as _dt
    _JOBS[job] = {"status": "running", "steps": [], "result": None, "error": None,
                  "started": _dt.datetime.now().strftime("%H:%M:%S")}

    def work():
        try:
            r = refresh(store(), PROJECT_ROOT, groups=body.groups or None,
                        datasets=body.datasets or None, sources=tuple(body.sources),
                        fred_key=body.fred_key or None, label=body.label,
                        only_default=not body.all_datasets,
                        progress=lambda m: _JOBS[job]["steps"].append(m))
            _JOBS[job].update(status="done", result=js(r))
        except Exception as exc:                  # reported, not raised
            _JOBS[job].update(status="failed", error=str(exc))
    threading.Thread(target=work, daemon=True).start()
    return {"job": job}


@router.get("/macro/refresh")
def refresh_jobs() -> list[dict]:
    """Every refresh started since the backend started, the latest first."""
    return [{"job": k, "status": v["status"], "started": v.get("started"),
             "step": (v["steps"] or [""])[-1]} for k, v in reversed(list(_JOBS.items()))]


@router.get("/macro/refresh/{job}")
def refresh_status(job: str) -> dict:
    j = _JOBS.get(job)
    if j is None:
        raise HTTPException(404, f"No refresh job {job!r}")
    return {"status": j["status"], "steps": j["steps"], "step": (j["steps"] or [""])[-1],
            "result": j["result"], "error": j["error"]}


@router.post("/macro/import")
async def do_import(file: UploadFile = File(...), source: str = Form(...),
                    dataset: str = Form(...), country: str = Form(""),
                    freq: str = Form(""), unit: str = Form(""),
                    label: str = Form("")) -> dict:
    """Add one file's series as a new vintage (QCB, the Planning Council, the
    Ministry of Finance, an SDMX-CSV from the IMF portal)."""
    suffix = Path(file.filename or "upload.csv").suffix or ".csv"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / f"upload{suffix}"
        with p.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        try:
            r = import_file(store(), p, source, dataset, country=country,
                            freq=freq or None, unit=unit, label=label)
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc
    return js(r)


@router.get("/macro/search")
def search(q: str = "", country: str | None = None, source: str | None = None,
           limit: int = 200, vintage: str | None = None) -> list[dict]:
    return js(store().search(q, vintage or None, limit=limit, source=source or None,
                             country=country or None))


@router.get("/macro/series")
def series(sid: str, vintage: str | None = None) -> dict:
    st = store()
    s = st.series(vintage)
    row = s[s["series_id"] == sid]
    if row.empty:
        raise HTTPException(404, f"No series {sid!r} in the store")
    o = st.observations(vintage, [sid])
    a = st.annual(sid, vintage)
    la = str(row.iloc[0].get("last_actual") or "").strip()
    last = int(la[:4]) if la[:4].isdigit() else last_actual_guess(list(a.index))
    return js({"series": row.iloc[0].to_dict(), "observations": o,
               "annual": [{"year": int(k), "value": float(v), "actual": int(k) <= last}
                          for k, v in a.items()]})


@router.get("/macro/concept/{cid}")
def concept_values(cid: str, vintage: str | None = None) -> dict:
    st = store()
    try:
        a = st.concept_annual(cid, vintage, PROJECT_ROOT)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return js({"concept": cid, "series_id": a.attrs.get("series_id", ""),
               "sd": st.concept_sd(cid, vintage, PROJECT_ROOT), "values": a})


class QuarterIn(BaseModel):
    reporting_date: str
    snapshot: str | None = Field(None, description="the snapshot to start from; "
                                                   "none for the live config")
    first_year: int | None = None
    vintage: str | None = None
    models: list[str] | None = Field(None, description="the rating models to fill "
                                                       "(ifrs9qdb.macro.quarter.MODELS); "
                                                       "none for all")
    keep_weights: list[str] = Field(default_factory=list,
                                    description="the models whose scenario weights stay as "
                                                "they are; the others go to automatic")


def _dirs(label: str | None) -> tuple[Path, Path]:
    if label:
        d = Path(SNAPSHOTS_ROOT) / label
        if not d.is_dir():
            raise HTTPException(404, f"No snapshot {label!r}")
        return d / "config", d / "static"
    cfg = CONFIG_DIR if (CONFIG_DIR / "model_inputs.yml").is_file() else \
        Path(__import__("ifrs9qdb").__file__).parent / "config"
    stat = STATIC_DIR if STATIC_DIR.is_dir() else \
        Path(__import__("ifrs9qdb").__file__).parent / "static"
    return cfg, stat


def _propose(body: QuarterIn) -> dict:
    cfg, stat = _dirs(body.snapshot)
    p = propose(store(), cfg, stat, body.reporting_date, vintage=body.vintage,
                project_root=PROJECT_ROOT, first_year=body.first_year,
                models=body.models, keep_weights=body.keep_weights)
    if not p.get("ok"):
        raise HTTPException(400, p.get("reason", "Nothing to propose."))
    return p


@router.get("/macro/models")
def quarter_models() -> dict:
    """The rating models a config update can fill."""
    return {"models": MODELS}


@router.post("/macro/propose")
def quarter_propose(body: QuarterIn) -> dict:
    """What the config would hold, and every value that moves."""
    p = _propose(body)
    return js({k: v for k, v in p.items()
               if not k.startswith("_") and k != "model_inputs_text"})


@router.post("/macro/apply")
def quarter_apply(body: QuarterIn) -> dict:
    """Write the proposal into a DRAFT snapshot (body.snapshot)."""
    if not body.snapshot:
        raise HTTPException(400, "Name the draft snapshot to write into.")
    p = _propose(body)
    r = apply_quarter(p, body.snapshot, snapshots_root=SNAPSHOTS_ROOT)
    if not r.get("ok"):
        raise HTTPException(400, r.get("message", "Could not write the draft."))
    return js(r)
