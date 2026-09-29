"""
Running the pipeline.

A run is started in the BACKGROUND and polled, because reading 117,000
collateral allocations and building 82,000 monthly EAD points takes long enough
that an HTTP request would time out and the browser would look hung.
"""
from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from ifrs9qdb.etl.pipeline import PENDING, PRODUCED, next_run_id, run_etl
from ifrs9qdb.etl.read_inputs import INPUT_SPECS, detect_format, resolve_input_path

router = APIRouter(tags=["etl"])
from .. import settings  # noqa: E402
from ..settings import RUNS_DIR, UPLOAD_DIR  # noqa: E402

INPUT_DIR = settings.input_dir()

_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()


@router.get("/etl/inputs")
def inspect_inputs(input_dir: str | None = None) -> dict:
    """What is in the input folder, before committing to a run.

    Reports the format detected from each file's BYTES rather than its
    extension: several extracts arrive as SQL*Plus HTML named `.xls`, and which
    ones has changed between quarters.
    """
    d = Path(input_dir) if input_dir else INPUT_DIR
    files = []
    for spec in INPUT_SPECS:
        p = resolve_input_path(d, spec) if d.is_dir() else None
        files.append({
            "name": spec.name,
            "expected": spec.file,
            "found": p.name if p else None,
            "format": detect_format(p) if p else None,
            "size_mb": round(p.stat().st_size / 1e6, 2) if p else None,
            "description": spec.description,
        })
    missing = [f["expected"] for f in files if not f["found"]]
    return {
        "input_dir": str(d.resolve() if d.exists() else d),
        "exists": d.is_dir(),
        "files": files,
        "missing": missing,
        "ready": d.is_dir() and not missing,
        "next_run_id": next_run_id(RUNS_DIR),
    }


class RunRequest(BaseModel):
    input_dir: str | None = None
    reporting_date: str | None = None
    run_id: str | None = None


@router.post("/etl/run")
def start_run(req: RunRequest) -> dict:
    """Start a run and return a job id to poll."""
    src = Path(req.input_dir) if req.input_dir else INPUT_DIR
    if not src.is_dir():
        raise HTTPException(400, f"No input directory at {src}")

    job_id = uuid.uuid4().hex[:12]
    with _LOCK:
        _JOBS[job_id] = {"status": "running", "step": "starting",
                         "message": "Starting…", "result": None}

    def progress(step, message):
        with _LOCK:
            _JOBS[job_id].update(step=step, message=message)

    def work():
        try:
            r = run_etl(src, RUNS_DIR, reporting_date=req.reporting_date,
                        run_id=req.run_id,
                        static_dir=settings.static_dir_for_run(),
                        config_dir=settings.config_dir_for_run(),
                        progress=progress,
                        on_validation_error=settings.on_validation_error(),
                        run_config=settings.run_config(),
                        project_root=settings.PROJECT_ROOT,
                        input_source={"kind": "folder",
                                      "details": {"path": str(src)}})
            with _LOCK:
                _JOBS[job_id].update(
                    status="done" if r.ok else "failed",
                    message="Finished" if r.ok else (r.error or "Failed"),
                    result=r.as_dict())
        except Exception as exc:
            import traceback as _tb
            with _LOCK:
                _JOBS[job_id].update(status="failed",
                                     message=f"{type(exc).__name__}: {exc}",
                                     traceback=_tb.format_exc())

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": job_id}


@router.get("/etl/run/{job_id}")
def run_status(job_id: str) -> dict:
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "No such job")
    return {"job_id": job_id, **job}


@router.get("/etl/coverage")
def coverage() -> dict:
    """Which of the eighteen output files the port produces today.

    Stated up front rather than discovered after a run: the port is not
    finished, and a run that wrote fourteen of eighteen files without saying so
    would be worse than one that says it.
    """
    return {"produced": PRODUCED, "pending": PENDING,
            "reference": ["Portfolios.csv", "Ratings.csv", "RatingTypes.csv",
                          "PortfolioRatingType.csv", "CollateralType.csv",
                          "FxRate.csv"]}




@router.post("/etl/upload")
async def upload(files: list[UploadFile] = File(...)) -> dict:
    """Take source extracts uploaded from the browser.

    Written to a staging folder rather than straight into a run, so a partial
    or mistaken upload can be replaced before anything is built from it.
    """
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        if not f.filename:
            continue
        dest = UPLOAD_DIR / Path(f.filename).name
        dest.write_bytes(await f.read())
        saved.append({"name": dest.name,
                      "size_mb": round(dest.stat().st_size / 1e6, 2),
                      "format": detect_format(dest)})
    return {"upload_dir": str(UPLOAD_DIR.resolve()), "saved": saved}


@router.delete("/etl/upload")
def clear_uploads() -> dict:
    """Empty the staging folder, so a re-upload cannot mix two quarters."""
    removed = 0
    if UPLOAD_DIR.is_dir():
        for p in UPLOAD_DIR.iterdir():
            if p.is_file():
                p.unlink()
                removed += 1
    return {"removed": removed}


@router.get("/config")
def read_config() -> dict:
    """The model configuration, as text, with the values that move a number
    pulled out so they can be read without parsing YAML."""
    import yaml
    cfg_dir = settings.config_dir_for_run() or \
        Path(__import__("ifrs9qdb").__file__).parent / "config"
    out = {"config_dir": str(cfg_dir), "files": {}, "summary": {}}
    for name in ("model.yml", "model_inputs.yml"):
        p = cfg_dir / name
        if p.is_file():
            out["files"][name] = p.read_text()
    try:
        mc = yaml.safe_load((cfg_dir / "model.yml").read_text())
        mi = yaml.safe_load((cfg_dir / "model_inputs.yml").read_text())
        comp = mc["models"]["internal_v4_production"]["mev_components"]
        out["summary"] = {
            "ttc_anchor_pd": mc.get("ttc_anchor_pd"),
            "horizons": mc.get("horizons", {}),
            "ecl": mc.get("ecl", {}),
            "mev_components": [
                {"variable": c["variable"], "weight": c.get("weight"),
                 "coefficient": c.get("coefficient"),
                 "intercept": c.get("intercept"),
                 "standard_deviation": c.get("standard_deviation")}
                for c in comp],
            "mev_forecasts": mi.get("mev_forecasts", {}).get("forecasts", {}),
            "scenario_weights":
                mi.get("internal_scenario_weights", {}).get("explicit_weights", {}),
        }
    except Exception as exc:
        out["summary_error"] = f"{type(exc).__name__}: {exc}"
    return out


class ConfigWrite(BaseModel):
    name: str
    content: str


@router.put("/config")
def write_config(req: ConfigWrite) -> dict:
    """Save a config file, after checking it still parses.

    Writing YAML that does not parse would break the next run with an error far
    from its cause, so it is validated here and rejected with the parse error.
    """
    import yaml
    if req.name not in ("model.yml", "model_inputs.yml"):
        raise HTTPException(400, "Only model.yml and model_inputs.yml are editable")
    try:
        yaml.safe_load(req.content)
    except yaml.YAMLError as exc:
        raise HTTPException(400, f"That is not valid YAML: {exc}")
    p = settings.CONFIG_DIR / req.name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(req.content)
    return {"saved": req.name, "path": str(p)}
