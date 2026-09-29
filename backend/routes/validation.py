"""Validation endpoints."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ifrs9qdb.validation import validate_run
from .runs import _output_dir

router = APIRouter(tags=["validation"])
from ..settings import RUNS_DIR  # noqa: E402


@router.get("/validation/{run_id}")
def validate(run_id: str) -> dict:
    """Every check that can see this run, passes included.

    Passes are returned as well as failures: a report showing only failures
    cannot be read as evidence that anything was checked.
    """
    od = _output_dir(RUNS_DIR / run_id)
    if od is None:
        raise HTTPException(404, f"No run named {run_id!r}")
    result = validate_run(od.parent if od.name.lower() == "output" else od)
    return {"summary": result.summary(),
            "issues": [i.as_dict() for i in result.issues]}
