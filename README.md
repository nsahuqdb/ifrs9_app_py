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
# 1. backend -- the project folder holds config, versions, runs and the log
IFRS9_PROJECT_ROOT=/path/to/project uvicorn backend.main:app --reload --port 8000

# 2. front end, in a second terminal
streamlit run app.py
```

The front end opens on <http://localhost:8501>; the generated API reference is
at <http://127.0.0.1:8000/docs>. If the backend is on another host or port:

```bash
IFRS9_BACKEND=http://10.0.0.5:8000 streamlit run app.py
```

## The project folder

The layout is the R app's, so the two apps can share one folder:

```
<project>/
  config.yml                run settings: paths, on_validation_error,
                            the model (run.internal_model), approval
                            (separation of duties), upload limit
  config/                   model.yml, model_inputs.yml, overlays.yml,
                            validation_suppressions.yml, calculator_versions.yml
  data-raw/static/          the static reference tables
  config_snapshots/         config versions: frozen config/ + static/ + config.yml
  runs/                     one folder per run
  logs/etl_audit.jsonl      the project audit log
  input/                    the configured input folder
  drops/                    data-team drop folders (paths.data_drop_root)
```

A fresh project is seeded from the app's own `config.yml`, `config/` and
`data-raw/` on first start, and never overwritten after. Each location can be
overridden on its own: `IFRS9_RUNS_DIR`, `IFRS9_CONFIG_DIR`,
`IFRS9_STATIC_DIR`, `IFRS9_CONFIG`, `IFRS9_SNAPSHOTS_DIR`, `IFRS9_INPUT_DIR`,
`IFRS9_DATA_DROP_ROOT`, `IFRS9_UPLOAD_DIR`, `IFRS9_AUDIT_LOG`,
`IFRS9_OVERLAYS`. `IFRS9_USER` names who is acting (the app has no login of
its own; the R app reads the OS user).

A run folder is the R engine's too:

```
runs/run_00001/
  Output/                   the LIC files, FinalEclReport.csv, per-scenario
                            reports, any overlaid report
  config_used/              the config the run froze, with config_used.yml
  overrides/                rating, stage and restructuring overrides applied
  reports/                  manifest.json, validation.csv, readiness.csv,
                            readiness_funnel.csv, run_status.yml
```

Runs, inputs and uploads are real portfolio data and are never committed;
`runs/`, `input/`, `uploads/`, `drops/` and `logs/` are in `.gitignore`.

## A quarter, in the app

1. **Run the pipeline** — pick the input (configured folder, a data-drop
   folder, or a zip), **Validate inputs** (structure, then every input check
   as a preview), pick the config version, run type and purpose, then
   **Pre-run check**: the config, static and input checks, and the
   pricing-readiness dry run — which contracts would get no ECL, which LIC
   would leave blank, which are priced from incomplete inputs, with the
   reasons, the fixes and the row funnel. Start stays disabled while any
   unsuppressed ERROR stands.
2. The run **pauses** after the customer view is computed: add rating, stage
   (worsening only) or restructuring overrides, each with a reason; Continue
   finishes the run, Cancel removes it.
3. An official run lands in the **Approval queue**; another user approves or
   rejects it with a reason (separation of duties is enforced when
   `approval.enforce_separation_of_duties` is true).
4. **Browse runs** shows every run: manifest, validation, readiness,
   overrides, reconciliation, outputs, the export package, and overlays.

See `APP_PARITY.md` for the page-by-page comparison with the R app, and the
engine's `PRICING_READINESS.md` for what the readiness check covers.

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
  settings.py   where everything lives: the project folder and its overrides
  routes/       health, runs, runs_detail, workflow (the phased run), ecl,
                analytics, stress, etl, validation, governance, admin -
                thin adapters over the package
  assistant/    the in-app assistant and its read-only tools
frontend/
  api.py        the only place that talks to the backend
  ui.py         shared presentation: theme, formatting, layout helpers
  views/        one module per page
app.py          the Streamlit entry point and navigation
config.yml, config/, data-raw/   the defaults a new project is seeded from
tests/          API tests; set IFRS9_PROJECT_ROOT to a project with runs to
                run the ones that need runs
```

The pages, grouped as in the navigation: **Runs** (browse runs, run the
pipeline, approval queue); **Config** (config versions, calculator versions,
ECL overlays, validation suppressions, live configuration, model
assumptions); **Portfolio** (overview, staging, concentration, distributions,
segments, risk parameters, scenarios, data quality, validation);
**Comparison** (movement, attribution, migration, reconcile & export);
**Audit log**; **Stress testing** (packages, comparison, lever sensitivity,
reverse stress, roll forward, what-if, staging threshold, macro path); and
**Help** (assistant, how this works).
