# Running the app

## Windows: one file

`start_ifrs9.bat` does everything. Put it in the folder that should hold the
two repositories (for example `Documents\IFRS9_apps`) and double-click it:

* the first time it downloads `ifrs9qdb_py` and `ifrs9_app_py` (git when
  installed, else the branch's zip), finds Python 3.10 or later (or installs
  Python 3.12 for the user), creates a virtual environment in
  `%LOCALAPPDATA%\ifrs9_app\venv`, installs the requirements, starts the
  backend and the interface and opens the browser;
* every later time it fetches the latest code, reinstalls only when a
  `pyproject.toml` changed, and restarts the app.

An update never overwrites the configuration, runs, config versions, macro
store or logs: with git, a file changed on this computer that the new code
also changes stops that repository's update (the file names are listed and
the app starts on the current code); from a zip, only new default files are
added to `config/` and `data-raw/`. The branch, the ports and a proxy are set
at the top of the file. Each step's output is in `launcher_logs`.

By hand, it is two processes, as with the transaction model app.

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
