# Running the app

Two processes, as with the transaction model app.

## 1. Backend

```bash
IFRS9_RUNS_DIR=/path/to/your/runs \
uvicorn backend.main:app --reload --port 8000
```

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

```bash
pip install -e ".[api,ui,dev]"
```

## Where the runs go

Point `IFRS9_RUNS_DIR` at the same `runs/` folder the R app uses — the layout
is identical:

```
runs/
  run_00001/
    Output/
      FinalEclReport.csv        analytics need this
      StPD.csv, Ratings.csv,    stress testing needs these
      AccountMaster_1.csv, ...
```

A run with only the report still works for the portfolio pages; the stress
pages will say which files are missing rather than failing obscurely.
