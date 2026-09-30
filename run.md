# Running the app

Two processes, as with the transaction model app.

## 1. Backend

```bash
IFRS9_PROJECT_ROOT=/path/to/project \
uvicorn backend.main:app --reload --port 8000
```

The project folder holds `config.yml`, `config/`, `data-raw/static/`, the
config versions, `runs/` and `logs/etl_audit.jsonl` -- the R app's layout, so
both apps can share one. A new folder is seeded from this app's defaults on
first start. `IFRS9_RUNS_DIR` and the other `IFRS9_*` variables override one
location at a time (see README).

Interactive API documentation: <http://127.0.0.1:8000/docs>

## 2. Frontend

In a second terminal:

```bash
streamlit run app.py
```

Opens on <http://localhost:8501>.

If the backend is on another host or port, set `IFRS9_BACKEND`:

```bash
IFRS9_BACKEND=http://10.0.0.5:8000 streamlit run app.py
```

## Install

From a folder holding both clones (`ifrs9qdb_py` and `ifrs9_app_py`), in a
virtual environment:

```bash
pip install -e "./ifrs9qdb_py[excel]"   # the engine first
pip install -e ./ifrs9_app_py           # then this app (".[dev]" adds the test tools)
```

After pulling a new version, run the second line again: it upgrades anything
the app now needs (the interface needs Streamlit 1.64 or later).

## Where the runs go

`<project>/runs/`, one folder per run, in the R engine's layout -- see
README, *The project folder*. A run with only the report still works for the
portfolio pages; the stress pages say which files are missing rather than
failing obscurely.

## Tests

```bash
pytest -q                                    # the API, without runs
IFRS9_PROJECT_ROOT=/path/to/project pytest -q    # and the tests that need runs
```
