# IFRS 9 ECL — application

The interface over the `ifrs9qdb` engine: a FastAPI backend that exposes the
calculation as JSON, and a Streamlit front end that draws it.

Two processes, and the separation is the point. The backend holds no
calculation of its own — every endpoint calls the package — and the front end
never imports the package, so a number on a screen and a number in a notebook
come from the same call and the interface cannot quietly compute something the
API would not return.

## Why this is separate from the engine

The R app and the R package split the same way: `ifrs9qdb` calculates,
`ifrs9_app` presents. Keeping that split here means the engine stays usable
from a script, a notebook or a scheduler, and the interface can be replaced
without touching a number.

## Install

The engine is a dependency, not a copy.

```bash
pip install -e ../ifrs9qdb_py        # the engine
pip install -e ".[dev]"              # this
```

## Running it

```bash
# 1. backend
IFRS9_RUNS_DIR=/path/to/runs uvicorn backend.main:app --reload --port 8000

# 2. front end, in a second terminal
streamlit run app.py
```

The front end opens on <http://localhost:8501>; the generated API reference is
at <http://127.0.0.1:8000/docs>.

If the backend is on another host or port:

```bash
IFRS9_BACKEND=http://10.0.0.5:8000 streamlit run app.py
```

## Where the runs go

Point `IFRS9_RUNS_DIR` at the same `runs/` folder the R app uses — the layout
is identical:

```
runs/
  run_00001/
    Output/
      FinalEclReport.csv        the analysis pages need this
      StPD.csv, Ratings.csv,    stress testing needs these
      AccountMaster_1.csv, ...
    config_used/                the config the run froze
    reports/manifest.json       what produced the run
    reports/run_status.yml      where it stands for approval
    reports/                    manifest, validation, run status
```

A run with only the report still works for the portfolio pages; the stress
pages say which files are missing rather than failing obscurely.

Runs are real portfolio data and are never committed. `runs/` is in
`.gitignore`.

## Deployment

IT deploy with Docker, which decides the architecture: one image, one port.

```bash
docker compose up --build
```

Runs, inputs and outputs are a mounted volume, not image content, so a
redeploy cannot lose a run and the image is identical across environments.

## What is here

```
backend/
  main.py       the FastAPI app: CORS, routers, startup banner
  routes/       health, runs, ecl, analytics, stress, etl, validation,
                governance - thin adapters over the package
frontend/
  api.py        the only place that talks to the backend
  ui.py         shared presentation: theme, formatting, layout helpers
  views/        one module per page (20)
```

The pages, in the order a quarter uses them: run the pipeline, configuration,
calculator versions, config snapshots; overview, staging, concentration, data quality,
validation; movement, reconcile & export; overlays, approval, accepted
findings, audit trail; stress packages, lever sensitivity, reverse stress,
roll forward; and help.

```
app.py          the Streamlit entry point and navigation
```
