"""
Backend entry point.

    uvicorn backend.main:app --reload --port 8000

Serves the engine, the analytics and the stress testing as JSON. It holds no
calculation of its own: every endpoint calls the ifrs9qdb package, so a figure
on a screen can be reproduced in a notebook with the same call and the two
cannot disagree.

Interactive documentation is at /docs.
"""
from __future__ import annotations

import os
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ifrs9qdb import __version__
from ifrs9qdb.audit_log import set_audit_log_path
from . import settings
from .routes import (admin, analytics, assistant, ecl, etl, governance, health,
                     runs, runs_detail, stress, validation, workflow)

RUNS_DIR = settings.RUNS_DIR
_SEEDED = settings.ensure_project()

# Every audit event the engine writes -- a run starting, a version promoted, a
# suppression added -- goes to the project's log, which the Audit log page
# reads. Pinned here once so it does not depend on the working directory.
set_audit_log_path(settings.AUDIT_LOG)


def _announce() -> None:
    print(f"  ifrs9qdb {__version__}")
    print(f"  project   {settings.PROJECT_ROOT.resolve()}")
    if _SEEDED:
        print(f"  seeded    {', '.join(_SEEDED)} from the app's defaults")
    print(f"  runs      {RUNS_DIR.resolve()}")
    if not RUNS_DIR.is_dir():
        print("  ! that directory does not exist yet - set IFRS9_RUNS_DIR")
    print(f"  audit log {settings.AUDIT_LOG}")
    print("  docs      http://127.0.0.1:8000/docs")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _announce()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="IFRS 9 ECL",
    version=__version__,
    description=(
        "Expected credit loss engine, analytics and stress testing for QDB. "
        "The calculation is the ifrs9qdb package; this is a transport over it."
    ),
    docs_url="/docs",
    openapi_url="/openapi.json",
)

# The Streamlit front end runs on its own port, so it is a different origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("IFRS9_ALLOWED_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (health.router, runs.router, runs_detail.router, ecl.router,
          analytics.router, stress.router, etl.router, workflow.router,
          validation.router, governance.router, admin.router,
          assistant.router):
    app.include_router(r, prefix="/api")


