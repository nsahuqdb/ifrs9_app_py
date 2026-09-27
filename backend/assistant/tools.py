"""What the assistant is allowed to look at.

Ten read-only tools over a run's outputs, its config and its validation
report. They are the ONLY way the assistant sees data, which is what makes
"ground every claim in an observation" enforceable rather than aspirational:
there is no path by which it can quote a number nobody handed it.

Every tool returns ``{ok, summary, ...}``. ``summary`` is the text the model
reads, so it is compact and already aggregated -- handing a model ten thousand
rows and hoping it sums them correctly is how a wrong number gets into a
committee pack. Where a result is chartable it also returns ``chart``, which
the app plots from the tool's own numbers rather than from anything the model
retyped.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

MAX_ROWS = 40
RUNS_DIR = Path(os.environ.get("IFRS9_RUNS_DIR", "runs"))

TOOL_CATALOGUE = "\n".join([
    "list_runs() -> every run with its id, extract date, contract count, "
    "provision and whether it carries a frozen config.",
    "list_files(run_id) -> the output CSVs a run wrote, with row counts.",
    "describe_file(run_id, file) -> a file's columns, with how many rows are "
    "populated and how many blank.",
    "aggregate(run_id, file, group_by, measure, fn) -> group-by aggregation. "
    "fn in {count,sum,mean,min,max,median}. measure may be omitted for count. "
    "group_by is one column or a list of columns.",
    "compare_runs(run_id_a, run_id_b, file, group_by, measure, fn) -> the same "
    "aggregation on two runs, joined with the difference and percent change. "
    "Use this for quarter-over-quarter questions.",
    "diff_files(run_id_a, run_id_b, file, key, columns) -> a row-level diff on "
    "`key`: rows added, rows removed, and how many rows changed per column.",
    "column_stats(run_id, file, column, top) -> a numeric summary, or the top "
    "values by frequency for a categorical column.",
    "filter_rows(run_id, file, where, columns, limit) -> rows matching `where`, "
    "a map of column to value.",
    "model_spec() -> the model specification from a run's FROZEN config: per-MEV "
    "intercept, coefficient, weight and standard deviation, the TTC anchor PD, "
    "the horizons and the scenario weights. Needs no aggregation over a run. "
    "USE THIS for any question about coefficients, weights or the macro model.",
    "validation_results(run_id, only_failures) -> the run's validation report: "
    "counts by severity and the checks that did not pass. only_failures "
    "defaults to true.",
])


# ------------------------------------------------------------- helpers -----
def _run_dir(run_id: str | None) -> Path | None:
    if not run_id:
        runs = _all_runs()
        return runs[0] if runs else None
    p = RUNS_DIR / str(run_id)
    return p if p.is_dir() else None


def _all_runs() -> list[Path]:
    if not RUNS_DIR.is_dir():
        return []
    return sorted((p for p in RUNS_DIR.iterdir() if p.is_dir()), reverse=True)


def _output(run: Path) -> Path | None:
    for name in ("Output", "output", "OUTPUT"):
        if (run / name).is_dir():
            return run / name
    return run if (run / "FinalEclReport.csv").is_file() else None


def _read(run_id: str | None, file: str) -> tuple[pd.DataFrame | None, str]:
    run = _run_dir(run_id)
    if run is None:
        return None, f"No run named {run_id!r}."
    out = _output(run)
    if out is None:
        return None, f"Run {run.name} has no output folder."
    name = str(file)
    if not name.lower().endswith(".csv"):
        name += ".csv"
    path = out / name
    if not path.is_file():
        have = ", ".join(sorted(p.name for p in out.glob("*.csv"))[:20])
        return None, f"{name} is not in run {run.name}. It holds: {have}"
    try:
        return pd.read_csv(path, low_memory=False), run.name
    except Exception as exc:
        return None, f"{name} could not be read: {exc}"


def _col(d: pd.DataFrame, name: str) -> str | None:
    """A column by name, ignoring case and punctuation."""
    want = "".join(ch for ch in str(name).lower() if ch.isalnum())
    for c in d.columns:
        if "".join(ch for ch in str(c).lower() if ch.isalnum()) == want:
            return c
    return None


def _table(d: pd.DataFrame, limit: int = MAX_ROWS) -> str:
    """A frame as compact text, truncated with the truncation stated."""
    if d is None or len(d) == 0:
        return "(no rows)"
    shown = d.head(limit)
    text = shown.to_string(index=False, max_colwidth=40)
    if len(d) > limit:
        text += f"\n… {len(d) - limit:,} more rows not shown"
    return text


def _fail(msg: str) -> dict:
    return {"ok": False, "summary": msg}


# --------------------------------------------------------------- tools -----
def list_runs(**_) -> dict:
    runs = _all_runs()
    if not runs:
        return _fail(f"No runs under {RUNS_DIR}.")
    rows = []
    for r in runs:
        out = _output(r)
        rep = out / "FinalEclReport.csv" if out else None
        n, ecl, date = None, None, ""
        if rep is not None and rep.is_file():
            try:
                d = pd.read_csv(rep, low_memory=False)
                n = len(d)
                c = _col(d, "ClaAmountOnbal")
                ecl = float(pd.to_numeric(d[c], errors="coerce").sum()) if c else None
                dc = _col(d, "ExtractDate")
                date = str(d[dc].iloc[0]) if dc is not None and len(d) else ""
            except Exception:
                pass
        rows.append({"run_id": r.name, "extract_date": date, "contracts": n,
                     "provision": ecl,
                     "frozen_config": (r / "config_used").is_dir()})
    frame = pd.DataFrame(rows)
    return {"ok": True, "summary": f"{len(rows)} runs:\n{_table(frame)}"}


def list_files(run_id: str | None = None, **_) -> dict:
    run = _run_dir(run_id)
    if run is None:
        return _fail(f"No run named {run_id!r}.")
    out = _output(run)
    if out is None:
        return _fail(f"Run {run.name} has no output folder.")
    rows = []
    for p in sorted(out.glob("*.csv")):
        try:
            n = sum(1 for _ in p.open(encoding="utf-8", errors="replace")) - 1
        except Exception:
            n = None
        rows.append({"file": p.name, "rows": n})
    return {"ok": True,
            "summary": f"Run {run.name} wrote {len(rows)} files:\n"
                       f"{_table(pd.DataFrame(rows), limit=60)}"}


def describe_file(run_id: str | None = None, file: str = "", **_) -> dict:
    d, where = _read(run_id, file)
    if d is None:
        return _fail(where)
    rows = [{"column": c, "populated": int(d[c].notna().sum()),
             "blank": int(d[c].isna().sum()),
             "example": str(d[c].dropna().iloc[0])[:40] if d[c].notna().any() else ""}
            for c in d.columns]
    return {"ok": True,
            "summary": f"{file} in run {where}: {len(d):,} rows, "
                       f"{len(d.columns)} columns.\n"
                       f"{_table(pd.DataFrame(rows), limit=80)}"}


_FNS = {"count", "sum", "mean", "min", "max", "median"}


def aggregate(run_id: str | None = None, file: str = "", group_by=None,
              measure: str | None = None, fn: str = "sum", **_) -> dict:
    d, where = _read(run_id, file)
    if d is None:
        return _fail(where)
    fn = str(fn).lower()
    if fn not in _FNS:
        return _fail(f"fn must be one of {sorted(_FNS)}, not {fn!r}.")

    keys = [group_by] if isinstance(group_by, str) else list(group_by or [])
    cols = [_col(d, k) for k in keys]
    if any(c is None for c in cols):
        missing = [k for k, c in zip(keys, cols) if c is None]
        return _fail(f"No column named {missing} in {file}. "
                     f"Columns: {', '.join(map(str, d.columns))}")

    if fn == "count":
        out = (d.groupby(cols, dropna=False).size().reset_index(name="count")
               if cols else pd.DataFrame({"count": [len(d)]}))
        value = "count"
    else:
        m = _col(d, measure or "")
        if m is None:
            return _fail(f"{fn} needs a measure column. "
                         f"Columns: {', '.join(map(str, d.columns))}")
        num = pd.to_numeric(d[m], errors="coerce")
        out = (d.assign(_m=num).groupby(cols, dropna=False)["_m"].agg(fn)
               .reset_index().rename(columns={"_m": m})
               if cols else pd.DataFrame({m: [getattr(num, fn)()]}))
        value = m

    out = out.sort_values(value, ascending=False).head(MAX_ROWS)
    chart = None
    if cols and len(out) > 1:
        chart = {"kind": "bar", "x": cols[0], "y": value,
                 "title": f"{fn} of {value} by {cols[0]} — {where}",
                 "rows": out.to_dict(orient="records")}
    return {"ok": True, "chart": chart,
            "summary": f"{fn} of {value} by {', '.join(cols) or '(all rows)'} "
                       f"in {file}, run {where}:\n{_table(out)}"}


def compare_runs(run_id_a: str = "", run_id_b: str = "", file: str = "",
                 group_by=None, measure: str | None = None,
                 fn: str = "sum", **_) -> dict:
    a = aggregate(run_id_a, file, group_by, measure, fn)
    b = aggregate(run_id_b, file, group_by, measure, fn)
    if not a.get("ok"):
        return a
    if not b.get("ok"):
        return b
    keys = [group_by] if isinstance(group_by, str) else list(group_by or [])
    fa = pd.DataFrame(a["chart"]["rows"]) if a.get("chart") else None
    fb = pd.DataFrame(b["chart"]["rows"]) if b.get("chart") else None
    if fa is None or fb is None:
        return _fail("Both runs need a grouped aggregation to be compared.")

    value = a["chart"]["y"]
    on = [c for c in fa.columns if c != value]
    m = fa.merge(fb, on=on, how="outer", suffixes=("_a", "_b")).fillna(0)
    m["diff"] = m[f"{value}_b"] - m[f"{value}_a"]
    m["pct_change"] = 100 * m["diff"] / m[f"{value}_a"].replace(0, pd.NA)
    m = m.reindex(m["diff"].abs().sort_values(ascending=False).index)
    return {"ok": True,
            "chart": {"kind": "bar", "x": on[0], "y": "diff",
                      "title": f"Change in {value} by {on[0]}: "
                               f"{run_id_a} → {run_id_b}",
                      "rows": m.head(MAX_ROWS).to_dict(orient="records")},
            "summary": f"{fn} of {value} by {', '.join(keys)} in {file}, "
                       f"{run_id_a} vs {run_id_b}:\n{_table(m)}"}


def diff_files(run_id_a: str = "", run_id_b: str = "", file: str = "",
               key: str = "", columns=None, **_) -> dict:
    da, wa = _read(run_id_a, file)
    if da is None:
        return _fail(wa)
    db, wb = _read(run_id_b, file)
    if db is None:
        return _fail(wb)
    ka, kb = _col(da, key), _col(db, key)
    if ka is None or kb is None:
        return _fail(f"No column named {key!r} in both files.")

    sa = set(da[ka].astype(str))
    sb = set(db[kb].astype(str))
    shared = [c for c in da.columns if c in db.columns and c != ka]
    if columns:
        want = [c for c in (columns if isinstance(columns, list) else [columns])]
        shared = [c for c in shared if _col(da, c) in shared or c in want]

    common = sa & sb
    a2 = da.drop_duplicates(ka).set_index(da.drop_duplicates(ka)[ka].astype(str))
    b2 = db.drop_duplicates(kb).set_index(db.drop_duplicates(kb)[kb].astype(str))
    idx = sorted(common)
    rows = []
    for c in shared:
        try:
            changed = (a2.loc[idx, c].astype(str).to_numpy()
                       != b2.loc[idx, c].astype(str).to_numpy()).sum()
        except Exception:
            continue
        if changed:
            rows.append({"column": c, "rows_changed": int(changed)})
    changes = pd.DataFrame(rows).sort_values("rows_changed", ascending=False) \
        if rows else pd.DataFrame(columns=["column", "rows_changed"])
    return {"ok": True,
            "summary": (f"{file}: {wa} vs {wb}, keyed on {key}.\n"
                        f"  in both: {len(common):,}\n"
                        f"  only in {wa}: {len(sa - sb):,}\n"
                        f"  only in {wb}: {len(sb - sa):,}\n"
                        f"columns that changed:\n{_table(changes)}")}


def column_stats(run_id: str | None = None, file: str = "", column: str = "",
                 top: int = 15, **_) -> dict:
    d, where = _read(run_id, file)
    if d is None:
        return _fail(where)
    c = _col(d, column)
    if c is None:
        return _fail(f"No column named {column!r} in {file}. "
                     f"Columns: {', '.join(map(str, d.columns))}")
    num = pd.to_numeric(d[c], errors="coerce")
    if num.notna().sum() > 0.8 * len(d):
        s = num.describe()
        stats = pd.DataFrame({"statistic": s.index, "value": s.to_numpy()})
        return {"ok": True,
                "summary": f"{c} in {file}, run {where} (numeric):\n"
                           f"{_table(stats)}\nblank: {int(num.isna().sum()):,}"}
    counts = (d[c].astype(str).value_counts().head(int(top))
              .reset_index().set_axis(["value", "rows"], axis=1))
    return {"ok": True,
            "chart": {"kind": "bar", "x": "value", "y": "rows",
                      "title": f"{c} by frequency — {where}",
                      "rows": counts.to_dict(orient="records")},
            "summary": f"{c} in {file}, run {where} (categorical), "
                       f"{d[c].nunique():,} distinct:\n{_table(counts)}"}


def filter_rows(run_id: str | None = None, file: str = "", where=None,
                columns=None, limit: int = 20, **_) -> dict:
    d, run = _read(run_id, file)
    if d is None:
        return _fail(run)
    sel = pd.Series(True, index=d.index)
    for k, v in (where or {}).items():
        c = _col(d, k)
        if c is None:
            return _fail(f"No column named {k!r} in {file}.")
        sel &= d[c].astype(str).str.strip() == str(v).strip()
    hit = d[sel]
    if columns:
        want = [_col(d, c) for c in (columns if isinstance(columns, list)
                                     else [columns])]
        hit = hit[[c for c in want if c]]
    return {"ok": True,
            "summary": f"{int(sel.sum()):,} rows match in {file}, run {run}:\n"
                       f"{_table(hit, limit=min(int(limit), MAX_ROWS))}"}


def model_spec(run_id: str | None = None, **_) -> dict:
    """The macro model, read from a run's FROZEN config.

    Config is not in the run's outputs, so this reads ``config_used`` rather
    than aggregating over anything. It is the right tool for every question
    about coefficients, weights and horizons.
    """
    from ifrs9qdb.analytics import (config_used, mev_weights_table,
                                    scenario_severity, scenario_weights)

    run = _run_dir(run_id)
    if run is None:
        return _fail(f"No run named {run_id!r}.")
    out = _output(run) or run
    cu = config_used(out)
    if cu is None:
        return _fail(f"Run {run.name} has no frozen config (config_used), so "
                     "its model specification cannot be shown. A run made "
                     "before that was added cannot be explained this way.")

    import yaml
    model = yaml.safe_load((cu["config"] / "model.yml").read_text(encoding="utf-8"))
    mevs = mev_weights_table(out)
    weights = scenario_weights(cu["config"])
    severity = scenario_severity(out)

    horizons = (model or {}).get("horizons", {}) or {}
    parts = [f"Model specification frozen by run {run.name}.",
             f"TTC anchor PD: {(model or {}).get('ttc_anchor_pd')}",
             f"Horizons: {horizons}",
             "", "MEV components:", _table(mevs),
             "", "Scenario weights as written in the config:", _table(weights),
             "", "Scenario severity:", _table(severity)]
    return {"ok": True, "summary": "\n".join(parts)}


def validation_results(run_id: str | None = None, only_failures: bool = True,
                       **_) -> dict:
    run = _run_dir(run_id)
    if run is None:
        return _fail(f"No run named {run_id!r}.")
    candidates = [run / "reports" / "validation.csv", run / "validation.csv"]
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        return _fail(f"Run {run.name} has no validation report. The app's "
                     "Validation page runs the checks against a run.")
    try:
        d = pd.read_csv(path)
    except Exception as exc:
        return _fail(f"The validation report could not be read: {exc}")

    sev = _col(d, "severity")
    status = _col(d, "passed") or _col(d, "status")
    counts = d[sev].value_counts().to_dict() if sev else {}
    failed = d
    if status is not None:
        col = d[status]
        ok = col.astype(str).str.lower().isin(("true", "pass", "passed", "1"))
        failed = d[~ok]
    lines = [f"Validation for run {run.name}: {len(d):,} checks, "
             f"{len(failed):,} not passing.",
             f"by severity: {counts}"]
    lines.append(_table(failed if only_failures else d))
    return {"ok": True, "summary": "\n".join(lines)}


_TOOLS = {
    "list_runs": list_runs, "list_files": list_files,
    "describe_file": describe_file, "aggregate": aggregate,
    "compare_runs": compare_runs, "diff_files": diff_files,
    "column_stats": column_stats, "filter_rows": filter_rows,
    "model_spec": model_spec, "validation_results": validation_results,
}


def execute_tool(name: str, args: dict | None = None) -> dict:
    """Run one tool. A failure is a result, not an exception.

    The model has to be able to read what went wrong and try something else;
    a traceback ends the conversation and tells the user nothing.
    """
    fn = _TOOLS.get(str(name))
    if fn is None:
        return _fail(f"There is no tool called {name!r}. "
                     f"Available: {', '.join(sorted(_TOOLS))}.")
    try:
        return fn(**(args or {}))
    except TypeError as exc:
        return _fail(f"{name} was called with arguments it does not take: {exc}")
    except Exception as exc:
        return _fail(f"{name} failed: {exc}")
