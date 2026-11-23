"""The assistant's main tools: questions as a user asks them, answered with
the same analytics functions the pages call -- so a figure in a chat answer is
the figure on the page.

Each tool returns ``{ok, summary, table?, chart?, cites?}``:

* ``summary`` -- compact text the model reads (already aggregated; a model
  that sums ten thousand rows gets a number wrong sooner or later);
* ``table``   -- ``{title, columns, rows}`` the app shows as a real table, with
  an Excel download, exactly as the tool computed it;
* ``chart``   -- a chart spec the app draws from those same rows;
* ``cites``   -- knowledge chunks behind an answer, for citations.

A tool never raises: a problem is a result the model can read and act on
(ask the user, try another tool), not a stack trace.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import knowledge as K

MAX_ROWS = 40
STAGES = ["Stage 1", "Stage 2", "Stage 3"]

# ------------------------------------------------------------ run lookup --


def _runs() -> list[dict]:
    """Every run with a report, newest first, as the Browse runs page lists
    them (id, portfolio date, type, status)."""
    from ..routes import runs as R
    try:
        rows = [r for r in R.list_runs() if r.get("has_report")]
    except Exception:
        return []
    return sorted(rows, key=lambda r: r["run_id"], reverse=True)


def resolve_run(ref, focus: str | None = None) -> tuple[str | None, str]:
    """A run named any way a person would: an id, a number ("run 2", "2"),
    "latest", "previous", a date ("2026-09-30", "Sep 2026", "Q3 2026").
    Returns (run_id, problem)."""
    runs = _runs()
    if not runs:
        return None, "There are no runs with a report yet."
    ids = [r["run_id"] for r in runs]
    s = str(ref or "").strip().lower()
    if not s or s in ("current", "this", "selected", "focus", "this run"):
        return (focus if focus in ids else ids[0]), ""
    if s in ("latest", "last", "newest", "most recent"):
        return ids[0], ""
    if s in ("previous", "prior", "last quarter", "before"):
        base = focus if focus in ids else ids[0]
        i = ids.index(base)
        return (ids[i + 1], "") if i + 1 < len(ids) else (None, f"{base} is the oldest run.")
    if s in ids:
        return s, ""
    for r in ids:
        if r.lower() == s:
            return r, ""
    m = re.fullmatch(r"(?:run[\s_#-]*)?0*(\d+)", s)
    if m:
        for r in ids:
            if re.search(r"(\d+)$", r) and int(re.search(r"(\d+)$", r).group(1)) == int(m.group(1)):
                return r, ""
    # a date or a quarter: match the portfolio date
    hits = [r for r in runs if _date_matches(s, str(r.get("portfolio_date") or ""))]
    if hits:
        official = [r for r in hits if r.get("run_type") == "official"]
        return (official or hits)[0]["run_id"], ""
    return None, (f"No run matches {ref!r}. Runs: "
                  + ", ".join(f"{r['run_id']} ({r.get('portfolio_date')}, "
                              f"{r.get('run_type')}, {r.get('status')})" for r in runs[:10]))


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _date_matches(s: str, date: str) -> bool:
    try:
        d = datetime.strptime(date[:10], "%Y-%m-%d")
    except ValueError:
        return False
    if s[:10] == date[:10]:
        return True
    y = re.search(r"(20\d\d)", s)
    if y and int(y.group(1)) != d.year:
        return False
    q = re.search(r"q([1-4])", s)
    if q:
        return (d.month - 1) // 3 + 1 == int(q.group(1))
    for name, n in _MONTHS.items():
        if name in s:
            return d.month == n
    return bool(y) and not q


def _report(run_id: str) -> pd.DataFrame:
    """The report the pages read (overlaid when an overlay is applied), kept
    in memory while the file is unchanged: a conversation asks of the same run
    many times."""
    from ..routes import analytics as A
    p = A.report_path(run_id)
    stamp = p.stat().st_mtime_ns if p is not None and p.is_file() else 0
    return _report_cached(run_id, str(p), stamp).copy()


from functools import lru_cache  # noqa: E402


@lru_cache(maxsize=12)
def _report_cached(run_id: str, path: str, stamp: int) -> pd.DataFrame:
    from ..routes import analytics as A
    return A._report(run_id)


# ------------------------------------------------------------- vocabulary --
MEASURES = {
    "ecl": "ECL (QAR)", "exposure": "Exposure (QAR)", "ead": "EAD (QAR)",
    "overlay": "Overlay (QAR)", "contracts": "Contracts", "customers": "Customers",
    "coverage": "Coverage %", "pd12": "12-month PD % (exposure-weighted)",
    "pd": "Lifetime PD % (exposure-weighted)", "lgd": "LGD % (exposure-weighted)",
}
_MEASURE_ALIASES = {
    "provision": "ecl", "ecl": "ecl", "loss": "ecl", "impairment": "ecl",
    "allowance": "ecl", "exposure": "exposure", "balance": "exposure",
    "outstanding": "exposure", "ead": "ead", "overlay": "overlay",
    "contracts": "contracts", "contract": "contracts", "facilities": "contracts",
    "accounts": "contracts", "count": "contracts", "customers": "customers",
    "customer": "customers", "clients": "customers", "coverage": "coverage",
    "coverage ratio": "coverage", "pd12": "pd12", "12m pd": "pd12",
    "12-month pd": "pd12", "pd": "pd", "lifetime pd": "pd", "lgd": "lgd",
}
DIMENSIONS = ["stage", "portfolio", "rating", "rating_type", "account_type",
              "customer", "maturity_band", "dpd_band", "watchlist", "restructured"]
_DIM_ALIASES = {
    "stage": "stage", "stages": "stage", "ifrs stage": "stage",
    "portfolio": "portfolio", "portfolios": "portfolio", "segment": "portfolio",
    "book": "portfolio", "rating": "rating", "grade": "rating", "ratings": "rating",
    "rating type": "rating_type", "scale": "rating_type", "rating_type": "rating_type",
    "account type": "account_type", "product": "account_type",
    "account_type": "account_type", "product type": "account_type",
    "customer": "customer", "customers": "customer", "client": "customer",
    "counterparty": "customer", "maturity": "maturity_band",
    "maturity band": "maturity_band", "maturity_band": "maturity_band",
    "remaining term": "maturity_band", "dpd": "dpd_band", "dpd band": "dpd_band",
    "dpd_band": "dpd_band", "days past due": "dpd_band",
    "watchlist": "watchlist", "restructured": "restructured",
}


def _measure(m) -> str | None:
    return _MEASURE_ALIASES.get(str(m or "ecl").strip().lower())


def _dims(by) -> tuple[list[str], list[str]]:
    raw = [by] if isinstance(by, str) else list(by or [])
    out, bad = [], []
    for b in raw:
        for part in re.split(r"\s*(?:,|\band\b|\bx\b|×)\s*", str(b)):
            if not part:
                continue
            d = _DIM_ALIASES.get(part.strip().lower())
            (out if d else bad).append(d or part)
    return out[:2], bad


def _with_dims(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    # the PD the provision is priced on: 100% in Stage 3, as the pages show it
    from ifrs9qdb.analytics.profile import effective_pd
    if "pd" in d.columns:
        d["pd"] = effective_pd(d)
        if "pd12" in d.columns:
            d["pd12"] = pd.to_numeric(d["pd12"], errors="coerce").where(
                pd.to_numeric(d["stage"], errors="coerce") != 3, 1.0)
    d["stage"] = d["stage"].map(lambda v: f"Stage {int(v)}" if pd.notna(v) and str(v).strip().lstrip("Stage ").isdigit()
                                else v) if "stage" in d else None
    if "maturity_date" in d.columns:
        ref = pd.to_datetime(d.get("extract_date"), errors="coerce")
        mat = pd.to_datetime(d["maturity_date"], errors="coerce")
        months = (mat - ref).dt.days / 30.44
        bins = [-np.inf, 0, 3, 6, 12, 24, 36, 60, 120, np.inf]
        labels = ["Past due/matured", "0–3m", "3–6m", "6–12m", "1–2y", "2–3y",
                  "3–5y", "5–10y", "10y+"]
        d["maturity_band"] = pd.cut(months, bins, labels=labels).astype(str)
    if "dpd" in d.columns:
        dpd = pd.to_numeric(d["dpd"], errors="coerce").fillna(0)
        d["dpd_band"] = pd.cut(dpd, [-np.inf, 0, 30, 60, 90, np.inf],
                               labels=["0", "1–30", "31–60", "61–90", "90+"]).astype(str)
    for f in ("watchlist", "restructured"):
        if f in d.columns:
            d[f] = d[f].map(lambda v: "Yes" if str(v).strip().lower() in
                            ("1", "true", "yes", "y", "1.0") else "No")
    if "customer_name" in d.columns:
        nm = d["customer_name"].fillna("").astype(str)
        cid = d["customer"].astype(str)
        d["customer"] = np.where((nm != "") & (nm != cid), cid + " · " + nm, cid)
    return d


def _apply_filters(d: pd.DataFrame, filters) -> tuple[pd.DataFrame, list[str], str]:
    """Filters as {dimension: value or [values]}; values matched without regard
    to case, a stage as 2 or "Stage 2", a customer by id or part of its name."""
    notes = []
    for k, v in (filters or {}).items():
        dim = _DIM_ALIASES.get(str(k).strip().lower()) or str(k)
        if dim not in d.columns:
            return d, notes, f"Cannot filter on {k!r}. Filters: {', '.join(DIMENSIONS)}."
        vals = v if isinstance(v, list) else [v]
        col = d[dim].astype(str)
        keep = pd.Series(False, index=d.index)
        for val in vals:
            sv = str(val).strip()
            if dim == "stage" and re.fullmatch(r"\d", sv):
                sv = f"Stage {sv}"
            exact = col.str.lower() == sv.lower()
            keep |= exact if exact.any() else col.str.lower().str.contains(re.escape(sv.lower()))
        if not keep.any():
            have = ", ".join(sorted(col.unique())[:15])
            return d, notes, f"No rows with {dim} = {v!r}. Values: {have}"
        d = d[keep]
        notes.append(f"{dim} = {', '.join(map(str, vals))}")
    return d, notes, ""


def _summarise(g: pd.core.groupby.DataFrameGroupBy | pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    def agg(x: pd.DataFrame) -> pd.Series:
        exp = x["exposure"].sum()
        w = x["exposure"].where(x["exposure"] > 0, 0)
        def wavg(c):
            if c not in x:
                return np.nan
            v = pd.to_numeric(x[c], errors="coerce")
            return 100 * float((v * w).sum() / w.sum()) if w.sum() else np.nan
        return pd.Series({
            "contracts": len(x),
            "customers": x["customer"].nunique() if "customer" in x else 1,
            "exposure": exp, "ead": x["ead"].sum() if "ead" in x else np.nan,
            "ecl": x["ecl"].sum(),
            "overlay": x["overlay"].sum() if "overlay" in x else 0.0,
            "coverage": 100 * x["ecl"].sum() / exp if exp else np.nan,
            "pd12": wavg("pd12"), "pd": wavg("pd"), "lgd": wavg("lgd"),
        })
    if keys:
        out = g.groupby(keys, dropna=False, observed=True).apply(agg, include_groups=False).reset_index()
    else:
        out = agg(g).to_frame().T
    return out


def _order(df: pd.DataFrame, col: str) -> pd.DataFrame:
    if col == "stage":
        return df.assign(_o=df[col].map({s: i for i, s in enumerate(STAGES)}).fillna(9)) \
            .sort_values("_o").drop(columns="_o")
    if col in ("maturity_band", "dpd_band"):
        return df   # already in band order from pd.cut
    if col == "rating":
        return df.assign(_o=df[col].map(_rating_rank)).sort_values("_o").drop(columns="_o")
    return df


def _rating_rank(r) -> float:
    s = str(r)
    m = re.match(r"QDB\s*(\d+)([+-]?)", s)
    if m:
        return int(m.group(1)) + {"+": -0.3, "": 0, "-": 0.3}[m.group(2)]
    order = ["Aaa", "Aa1", "Aa2", "Aa3", "A1", "A2", "A3", "Baa1", "Baa2", "Baa3",
             "Ba1", "Ba2", "Ba3", "B1", "B2", "B3", "Caa1", "Caa2", "Caa3", "Ca", "C"]
    return 100 + order.index(s) if s in order else 999


def _fmt(v, kind: str = "") -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    if isinstance(v, (int, np.integer)):
        return f"{v:,}"
    if isinstance(v, (float, np.floating)):
        if kind in ("pct", "coverage", "pd12", "pd", "lgd") or kind.endswith("%"):
            return f"{v:.2f}%"
        return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.4g}"
    return str(v)


def _text(df: pd.DataFrame, limit: int = MAX_ROWS) -> str:
    if df is None or not len(df):
        return "(no rows)"
    show = df.head(limit).copy()
    for c in show.columns:
        if pd.api.types.is_float_dtype(show[c]):
            pct = any(t in str(c).lower() for t in ("coverage", "pct", "%", "pd", "lgd", "share"))
            show[c] = show[c].map(lambda v: _fmt(v, "pct" if pct else ""))
    s = show.to_string(index=False, max_colwidth=70)
    if len(df) > limit:
        s += f"\n… {len(df) - limit:,} more rows not shown"
    return s


def _clean_num(v):
    """Floating noise out (1e-10 from a sum that should be 0), money to the
    cent, rates and PDs kept at full precision."""
    if isinstance(v, (float, np.floating)):
        if not np.isfinite(v):
            return None
        if abs(v) < 5e-9:
            return 0.0
        return round(float(v), 2) if abs(v) >= 1000 else round(float(v), 6)
    return v


_RATE_NAMES = {"coverage": "coverage %", "pd12": "12m PD %", "pd": "lifetime PD %",
               "lgd": "LGD %", "share_%": "share %", "share_of_ecl_%": "share of ECL %",
               "change_%": "change %", "pct_of_opening": "% of opening"}


def _table(df: pd.DataFrame, title: str, rates: bool = True) -> dict:
    """``rates``: the columns named coverage, pd12, pd, lgd hold percentages
    and are labelled so (the movement's lgd column is money and is not)."""
    df = df.copy()
    if rates:
        df = df.rename(columns={c: _RATE_NAMES[c] for c in df.columns if c in _RATE_NAMES})
    else:
        df = df.rename(columns={c: _RATE_NAMES[c] for c in df.columns
                                if c in ("change_%", "pct_of_opening", "share_%")})
    for c in df.columns:
        if pd.api.types.is_float_dtype(df[c]):
            df[c] = df[c].map(_clean_num).astype(object)
    df = df.replace({np.nan: None})
    return {"title": title, "columns": [str(c) for c in df.columns],
            "rows": df.to_dict(orient="records")}


def _fail(msg: str) -> dict:
    return {"ok": False, "summary": msg}


def _run_or_fail(run_id, focus):
    rid, why = resolve_run(run_id, focus)
    return rid, (None if rid else _fail(why))


# ------------------------------------------------------------------ tools --
def runs(focus: str | None = None, limit: int = 30, **_) -> dict:
    """Every run: id, portfolio date, type, status, contracts and provision."""
    rows = []
    for r in _runs()[:limit]:
        try:
            d = _report(r["run_id"])
            ecl, n = float(d["ecl"].sum()), len(d)
            exp = float(d["exposure"].sum())
            cov = 100 * ecl / exp if exp else None
        except Exception:
            ecl = n = cov = None
        rows.append({"run": r["run_id"], "portfolio_date": r.get("portfolio_date"),
                     "type": r.get("run_type"), "status": r.get("status"),
                     "contracts": n, "ecl": ecl, "coverage": cov,
                     "focus": "◀" if r["run_id"] == focus else ""})
    df = pd.DataFrame(rows)
    if not len(df):
        return _fail("There are no runs with a report yet.")
    return {"ok": True, "summary": f"{len(df)} runs (newest first):\n{_text(df)}",
            "table": _table(df, "Runs")}


def overview(run_id=None, focus=None, **_) -> dict:
    """Headline of one run: totals, by stage, by portfolio, overlay."""
    from ..routes import analytics as A
    rid, bad = _run_or_fail(run_id, focus)
    if bad:
        return bad
    s = A.summary(rid)
    d = _with_dims(_report(rid))
    st = _order(_summarise(d, ["stage"]), "stage")[
        ["stage", "customers", "contracts", "exposure", "ecl", "coverage"]]
    st["share_of_ecl_%"] = 100 * st["ecl"] / st["ecl"].sum()
    pf = _summarise(d, ["portfolio"]).sort_values("ecl", ascending=False)[
        ["portfolio", "contracts", "exposure", "ecl", "coverage"]]
    ov = float(d["overlay"].sum()) if "overlay" in d else 0.0
    head = (f"Run {rid}: {s['contracts']:,} contracts, {s['customers']:,} customers, "
            f"exposure {s['exposure']:,.0f}, ECL {s['ecl']:,.0f} "
            f"(coverage {s['coverage']:.2f}%)"
            + (f", of which management overlay {ov:,.0f}" if abs(ov) > 0.5 else "")
            + f". Concentration index {s['hhi']:.0f} ({s['hhi_band']}).")
    return {"ok": True,
            "summary": f"{head}\n\nBy stage:\n{_text(st)}\n\nBy portfolio:\n{_text(pf)}",
            "table": _table(st, f"{rid} · by stage"),
            "extra_tables": [_table(pf, f"{rid} · by portfolio")],
            "chart": {"kind": "bar", "x": "stage", "y": "ecl", "title": f"ECL by stage · {rid}",
                      "rows": st.to_dict(orient="records")}}


def breakdown(run_id=None, by="portfolio", measure="ecl", filters=None,
              focus=None, top: int = MAX_ROWS, **_) -> dict:
    """ECL, exposure, coverage, PD, LGD, counts by one or two dimensions."""
    rid, bad = _run_or_fail(run_id, focus)
    if bad:
        return bad
    m = _measure(measure)
    if m is None:
        return _fail(f"Unknown measure {measure!r}. Measures: {', '.join(MEASURES)}.")
    dims, unknown = _dims(by)
    if unknown:
        return _fail(f"Cannot break down by {unknown}. Dimensions: {', '.join(DIMENSIONS)}. "
                     "Sector is not in the ECL report; ask for portfolio or account type.")
    d = _with_dims(_report(rid))
    d, notes, err = _apply_filters(d, filters)
    if err:
        return _fail(err)
    where = f" ({'; '.join(notes)})" if notes else ""
    if not dims:
        t = _summarise(d, [])
        return {"ok": True, "summary": f"{rid}{where}: {MEASURES[m]} = {_fmt(t[m].iloc[0], m)}\n{_text(t)}",
                "table": _table(t, f"{rid}{where}")}
    if len(dims) == 1:
        k = dims[0]
        t = _summarise(d, [k])
        t = _order(t.sort_values(m, ascending=False), k) if k in ("stage", "rating", "maturity_band", "dpd_band") \
            else t.sort_values(m, ascending=False)
        if m in ("ecl", "exposure", "contracts", "customers", "ead", "overlay"):
            t[f"share_%"] = 100 * t[m] / t[m].sum() if t[m].sum() else np.nan
        cols = [k, m] + [c for c in ("contracts", "customers", "exposure", "ecl", "coverage", "share_%")
                         if c != m and c in t]
        t = t[cols].head(int(top))
        total = _summarise(d, [])[m].iloc[0]
        return {"ok": True,
                "summary": f"{MEASURES[m]} by {k}, run {rid}{where}. Total {_fmt(total, m)}.\n{_text(t)}",
                "table": _table(t, f"{MEASURES[m]} by {k} · {rid}{where}"),
                "chart": {"kind": "bar", "x": k, "y": m, "title": f"{MEASURES[m]} by {k} · {rid}",
                          "rows": t.to_dict(orient="records")}}
    a, b = dims
    long = _summarise(d, [a, b])[[a, b, m]]
    piv = long.pivot_table(index=a, columns=b, values=m, aggfunc="sum", fill_value=0)
    if b == "stage":
        piv = piv[[c for c in STAGES if c in piv.columns] + [c for c in piv.columns if c not in STAGES]]
    if m not in ("coverage", "pd12", "pd", "lgd"):
        piv["Total"] = piv.sum(axis=1)
        piv = piv.sort_values("Total", ascending=False)
    piv = piv.reset_index()
    piv = _order(piv, a) if a in ("stage", "rating", "maturity_band", "dpd_band") else piv
    piv.columns = [str(c) for c in piv.columns]
    return {"ok": True,
            "summary": f"{MEASURES[m]} by {a} and {b}, run {rid}{where}:\n{_text(piv)}",
            "table": _table(piv.head(int(top)), f"{MEASURES[m]} by {a} × {b} · {rid}{where}"),
            "chart": {"kind": "stacked", "x": a, "y": m, "color": b,
                      "title": f"{MEASURES[m]} by {a} and {b} · {rid}",
                      "rows": long.to_dict(orient="records")}}


def compare(run_a="previous", run_b=None, by=None, measure="ecl", filters=None,
            focus=None, **_) -> dict:
    """The same breakdown on two runs side by side, with the change."""
    rb, bad = _run_or_fail(run_b, focus)
    if bad:
        return bad
    ra, why = resolve_run(run_a, rb)
    if not ra:
        return _fail(why)
    if ra == rb:
        return _fail(f"Both sides are {ra}; name two different runs.")
    m = _measure(measure)
    if m is None:
        return _fail(f"Unknown measure {measure!r}. Measures: {', '.join(MEASURES)}.")
    dims, unknown = _dims(by)
    if unknown:
        return _fail(f"Cannot compare by {unknown}. Dimensions: {', '.join(DIMENSIONS)}.")
    dims = dims[:1]
    da, _, err = _apply_filters(_with_dims(_report(ra)), filters)
    db, notes, err2 = _apply_filters(_with_dims(_report(rb)), filters)
    if err or err2:
        return _fail(err or err2)
    sa, sb = _summarise(da, dims), _summarise(db, dims)
    if dims:
        k = dims[0]
        t = sa[[k, m]].merge(sb[[k, m]], on=k, how="outer", suffixes=(f" {ra}", f" {rb}")).fillna(0)
    else:
        k = "total"
        t = pd.DataFrame({k: ["All"], f"{m} {ra}": sa[m].to_numpy(), f"{m} {rb}": sb[m].to_numpy()})
    t["change"] = t[f"{m} {rb}"] - t[f"{m} {ra}"]
    t["change_%"] = 100 * t["change"] / t[f"{m} {ra}"].replace(0, np.nan)
    t = t.reindex(t["change"].abs().sort_values(ascending=False).index)
    if dims and m in ("ecl", "exposure", "contracts", "customers", "ead", "overlay"):
        tot = {k: "Total", f"{m} {ra}": sa[m].sum(), f"{m} {rb}": sb[m].sum()}
        tot["change"] = tot[f"{m} {rb}"] - tot[f"{m} {ra}"]
        tot["change_%"] = 100 * tot["change"] / tot[f"{m} {ra}"] if tot[f"{m} {ra}"] else np.nan
        t = pd.concat([t, pd.DataFrame([tot])], ignore_index=True)
    where = f" ({'; '.join(notes)})" if notes else ""
    biggest = ""
    if dims and len(t) > 1:
        r0 = t.iloc[0]
        biggest = (f" Largest move: {r0[k]} {_fmt(r0['change'])} "
                   f"({_fmt(r0['change_%'], 'pct')}).")
    return {"ok": True,
            "summary": f"{MEASURES[m]} {ra} → {rb}{where} by {k}.{biggest}\n{_text(t)}",
            "table": _table(t, f"{MEASURES[m]}: {ra} → {rb}{where}"),
            "chart": ({"kind": "bar", "x": k, "y": "change", "diverging": True,
                       "title": f"Change in {MEASURES[m]} by {k}: {ra} → {rb}",
                       "rows": t[t[k] != "Total"].to_dict(orient="records")} if dims else None)}


def movement(run_a="previous", run_b=None, level="book", member=None,
             focus=None, **_) -> dict:
    """Why the provision moved: the Movement page's bridge (derecognised, new
    business, exposure, stage, rating, macro, model, LGD, overlay) for the book,
    or per portfolio / stage / rating / account type / customer."""
    from ..routes import analytics as A
    from ifrs9qdb.analytics import BRIDGE_LEVELS, bridge_by, bridge_view
    rb, bad = _run_or_fail(run_b, focus)
    if bad:
        return bad
    ra, why = resolve_run(run_a, rb)
    if not ra:
        return _fail(why)
    lv = {"portfolio": "segment", "segment": "segment", "facility": "facility",
          "contract": "facility"}.get(str(level).lower(), str(level).lower())
    if lv not in BRIDGE_LEVELS:
        return _fail(f"level must be one of book, portfolio, stage, rating, account_type, customer, facility.")
    try:
        br = A._bridge(ra, rb)
    except Exception as exc:
        return _fail(f"The movement between {ra} and {rb} could not be built: {getattr(exc, 'detail', exc)}")
    if lv != "book" and not member:
        t = bridge_by(br["rows"], lv)
        keep = ["label", "opening", "derecognised", "new_business", "exposure", "stage",
                "rating", "macro", "model", "settings", "lgd", "overlay", "other", "closing", "change"]
        t = t[[c for c in keep if c in t.columns]]
        num = t.select_dtypes("number")
        keep_cols = [c for c in t.columns if c in ("label", "opening", "closing", "change")
                     or (c in num and (num[c].abs() > 0.5).any())]
        t = t[keep_cols]
        lv = "portfolio" if lv == "segment" else lv
        t = t.reindex(t["change"].abs().sort_values(ascending=False).index).rename(columns={"label": lv})
        r0 = t.iloc[0]
        return {"ok": True,
                "summary": (f"Movement {ra} → {rb} by {lv}. Largest change: {r0[lv]} "
                            f"{_fmt(r0['change'])} (from {_fmt(r0['opening'])} to {_fmt(r0['closing'])}).\n{_text(t)}"),
                "table": _table(t, f"Movement by {lv}: {ra} → {rb}", rates=False),
                "chart": {"kind": "bar", "x": lv, "y": "change", "diverging": True,
                          "title": f"Change in ECL by {lv}: {ra} → {rb}",
                          "rows": t.head(20).to_dict(orient="records")}}
    members = [member] if isinstance(member, str) else list(member or [])
    v = bridge_view(br["rows"], lv, members, 50)
    steps = pd.DataFrame(v["steps"])
    steps = steps[(steps["kind"] == "total") | (steps["amount"].abs() > 0.5)]
    t = steps[["label", "amount"]].rename(columns={"label": "step"})
    op, cl = v["opening"], v["closing"]
    t["pct_of_opening"] = 100 * t["amount"] / op if op else np.nan
    t.loc[t["step"].isin(["Opening", "Closing"]), "pct_of_opening"] = np.nan
    what = "the whole book" if lv == "book" else f"{lv} {', '.join(map(str, members))}"
    return {"ok": True,
            "summary": (f"ECL movement {ra} → {rb} for {what}: {_fmt(op)} → {_fmt(cl)} "
                        f"({_fmt(cl - op)}, {_fmt(100 * (cl - op) / op if op else np.nan, 'pct')}). "
                        f"Steps in the Movement page's order, each on top of the ones before, adding "
                        f"exactly to the change:\n{_text(t)}"),
            "table": _table(t, f"ECL movement {ra} → {rb} · {what}"),
            "chart": {"kind": "waterfall", "x": "step", "y": "amount",
                      "title": f"ECL movement {ra} → {rb}", "rows": t.to_dict(orient="records")}}


def migration(run_a="previous", run_b=None, kind="stage", focus=None, **_) -> dict:
    """Customers moving between stages (or rating grades) between two runs."""
    from ifrs9qdb.analytics import customer_stage_migration, rating_migration
    rb, bad = _run_or_fail(run_b, focus)
    if bad:
        return bad
    ra, why = resolve_run(run_a, rb)
    if not ra:
        return _fail(why)
    a, b = _report(ra), _report(rb)
    if str(kind).lower().startswith("r"):
        t = rating_migration(a, b, top=25, by_customer=True)
        return {"ok": True, "summary": f"Rating migration (customers) {ra} → {rb}:\n{_text(t)}",
                "table": _table(t, f"Rating migration {ra} → {rb}")}
    m = customer_stage_migration(a, b).copy()
    m["move"] = m.apply(lambda r: f"Stage {r['from']} → Stage {r['to']}", axis=1)
    m["direction"] = np.where(m["to"] > m["from"], "worse", np.where(m["to"] < m["from"], "better", "same"))
    m["ecl_change"] = m["ecl"] - m["ecl_prev"]
    t = m[["move", "direction", "customers", "exposure_prev", "exposure", "ecl_prev", "ecl", "ecl_change"]]
    mat = m.pivot_table(index="from", columns="to", values="customers", aggfunc="sum", fill_value=0)
    mat.index = [f"from Stage {i}" for i in mat.index]
    mat.columns = [f"to Stage {c}" for c in mat.columns]
    worse = int(m.loc[m["direction"] == "worse", "customers"].sum())
    better = int(m.loc[m["direction"] == "better", "customers"].sum())
    return {"ok": True,
            "summary": (f"Stage migration (customers in both runs) {ra} → {rb}: {worse} worse, "
                        f"{better} better.\nMatrix (customers):\n{mat.to_string()}\n\nMoves:\n{_text(t)}"),
            "table": _table(t, f"Stage moves {ra} → {rb}"),
            "extra_tables": [_table(mat.reset_index().rename(columns={"index": ""}),
                                    f"Stage migration matrix (customers) {ra} → {rb}")],
            "chart": {"kind": "bar", "x": "move", "y": "customers",
                      "title": f"Customers by stage move {ra} → {rb}",
                      "rows": t[t["direction"] != "same"].to_dict(orient="records")}}


def top(run_id=None, by="customer", measure="ecl", n=10, filters=None, focus=None, **_) -> dict:
    """The largest customers or contracts by ECL or exposure."""
    rid, bad = _run_or_fail(run_id, focus)
    if bad:
        return bad
    m = _measure(measure)
    if m not in ("ecl", "exposure", "ead", "overlay", "coverage"):
        return _fail("measure for top is ecl, exposure, ead, overlay or coverage.")
    d = _with_dims(_report(rid))
    d, notes, err = _apply_filters(d, filters)
    if err:
        return _fail(err)
    n = max(1, min(int(n or 10), 100))
    if str(by).lower().startswith(("contract", "facil", "account")):
        cols = [c for c in ("contract", "customer", "portfolio", "stage", "rating", "exposure", "ecl", "coverage")
                if c in d.columns or c == "coverage"]
        d = d.assign(coverage=100 * d["ecl"] / d["exposure"].where(d["exposure"] != 0))
        t = d.sort_values(m, ascending=False)[cols].head(n)
        level = "contracts"
    else:
        t = _summarise(d, ["customer"])
        first = d.groupby("customer").agg(portfolio=("portfolio", lambda s: ", ".join(sorted(set(map(str, s))))),
                                          stage=("stage", "max"), rating=("rating", "first"))
        t = t.merge(first, left_on="customer", right_index=True)
        t = t.sort_values(m, ascending=False)[["customer", "portfolio", "stage", "rating", "contracts",
                                               "exposure", "ecl", "coverage"]].head(n)
        level = "customers"
    tot = _summarise(d, [])[m].iloc[0]
    share = 100 * t[m].sum() / tot if tot and m != "coverage" else np.nan
    where = f" ({'; '.join(notes)})" if notes else ""
    return {"ok": True,
            "summary": (f"Top {n} {level} by {MEASURES[m]}, run {rid}{where}"
                        + (f"; together {_fmt(share, 'pct')} of the total" if share == share else "")
                        + f":\n{_text(t)}"),
            "table": _table(t, f"Top {n} {level} by {m} · {rid}{where}"),
            "chart": {"kind": "bar", "x": "customer" if level == "customers" else "contract", "y": m,
                      "horizontal": True, "title": f"Top {n} {level} by {MEASURES[m]} · {rid}",
                      "rows": t.to_dict(orient="records")}}


def customer(run_id=None, query="", focus=None, **_) -> dict:
    """One customer: every contract with stage, rating, DPD, flags, exposure,
    collateral, PD, LGD and ECL."""
    rid, bad = _run_or_fail(run_id, focus)
    if bad:
        return bad
    d = _report(rid)
    q = str(query or "").strip()
    if not q:
        return _fail("Name the customer (id or part of the name).")
    cid = d["customer"].astype(str)
    nm = d.get("customer_name", pd.Series("", index=d.index)).fillna("").astype(str)
    hit = d[(cid.str.lower() == q.lower())]
    if not len(hit):
        hit = d[cid.str.contains(re.escape(q), case=False) | nm.str.contains(re.escape(q), case=False)]
    if not len(hit):
        return _fail(f"No customer matches {q!r} in {rid}.")
    found = hit["customer"].astype(str).unique()
    if len(found) > 1:
        names = (hit.drop_duplicates("customer")[["customer", "customer_name"]]
                 if "customer_name" in hit else hit.drop_duplicates("customer")[["customer"]])
        return {"ok": True, "ambiguous": True,
                "summary": f"{len(found)} customers match {q!r}; ask which one:\n{_text(names, 15)}",
                "table": _table(names.head(30), f"Customers matching {q!r}")}
    cols = [c for c in ("contract", "portfolio", "account_type", "stage", "rating", "dpd", "watchlist",
                        "restructured", "exposure", "collateral", "collcov", "pd12", "pd", "lgd", "ead",
                        "ecl", "overlay", "maturity_date") if c in hit.columns]
    t = hit[cols].sort_values("ecl", ascending=False).copy()
    s3 = pd.to_numeric(t["stage"], errors="coerce") == 3 if "stage" in t else False
    for c in ("pd12", "pd"):                            # priced at 100% in Stage 3
        if c in t:
            t[c] = pd.to_numeric(t[c], errors="coerce").where(~s3, 1.0)
    for c in ("pd12", "pd", "lgd", "collcov"):          # fractions in the report
        if c in t:
            t[c] = 100 * pd.to_numeric(t[c], errors="coerce")
    t = t.rename(columns={"collcov": "collateral cover %"})
    name = str(hit["customer_name"].iloc[0]) if "customer_name" in hit else ""
    head = (f"Customer {found[0]}{' · ' + name if name and name != found[0] else ''}, run {rid}: "
            f"{len(t)} contract(s), exposure {hit['exposure'].sum():,.0f}, ECL {hit['ecl'].sum():,.0f}, "
            f"stage {', '.join(sorted(set(map(str, hit['stage']))))}, rating {', '.join(sorted(set(map(str, hit['rating']))))}.")
    return {"ok": True, "summary": f"{head}\n{_text(t)}",
            "table": _table(t, f"{found[0]} · contracts · {rid}")}


def staging(run_id=None, focus=None, **_) -> dict:
    """Why contracts are in Stage 2 and Stage 3 (the Staging page)."""
    from ..routes import analytics as A
    rid, bad = _run_or_fail(run_id, focus)
    if bad:
        return bad
    s = A.staging(rid, None)
    det = A.staging_detail(rid, None)
    trig = pd.DataFrame(s["triggers"])
    s3 = pd.DataFrame(det["stage3_drivers"])
    dpd = pd.DataFrame(det["dpd_by_stage"])
    return {"ok": True,
            "summary": (f"Staging of {rid} (Stage 2 DPD threshold {s['dpd_threshold']:g} days).\n"
                        f"Stage 2 triggers (a contract can have several):\n{_text(trig)}\n\n"
                        f"Stage 3 drivers:\n{_text(s3)}\n\nDays past due by stage:\n{_text(dpd)}\n"
                        f"Contracts whose stage differs from the rule: "
                        f"{det['consistency'].get('n_findings', len(det['findings']))}"),
            "table": _table(trig, f"Why contracts are in Stage 2 · {rid}"),
            "extra_tables": [_table(s3, f"Stage 3 drivers · {rid}"), _table(dpd, f"DPD by stage · {rid}")],
            "chart": ({"kind": "bar", "x": trig.columns[0], "y": "contracts" if "contracts" in trig else trig.columns[1],
                       "title": f"Stage 2 triggers · {rid}", "rows": trig.to_dict(orient="records")}
                      if len(trig) else None)}


def scenarios(run_id=None, focus=None, **_) -> dict:
    """The provision under each macro scenario and the weighted (booked) one,
    with the scenario weights the run used."""
    from ..routes import analytics as A
    rid, bad = _run_or_fail(run_id, focus)
    if bad:
        return bad
    s = A.scenarios(rid)
    if not s.get("available"):
        return _fail(f"Run {rid} has no per-scenario results: {s.get('reason')}")
    t = pd.DataFrame(s["comparison"])
    w = A.scenario_weights_used(rid)
    if w.get("ok"):
        t["weight_internal_%"] = t["scenario"].map(lambda k: 100 * w["internal"].get(k, np.nan))
        t["weight_external_avg_%"] = t["scenario"].map(lambda k: 100 * (w["external"] or {}).get(k, np.nan))
    keep = [c for c in ("scenario", "severity_z", "ecl", "weight_internal_%", "weight_external_avg_%",
                        "diff_vs_base", "pct_vs_base") if c in t.columns]
    t = t[keep]
    return {"ok": True,
            "summary": (f"Run {rid}: booked (probability-weighted) ECL {s['weighted']:,.0f}. The weights apply "
                        f"to the PDs before pricing, so the booked figure is not the weighted average of the "
                        f"scenario figures.\n{_text(t)}"),
            "table": _table(t, f"ECL by scenario · {rid}"),
            "chart": {"kind": "bar", "x": "scenario", "y": "ecl", "title": f"ECL by scenario · {rid}",
                      "rows": t.to_dict(orient="records")}}


def pd_curve(run_id=None, ratings=None, scale="Internal", years: int = 10, kind="cumulative",
             focus=None, **_) -> dict:
    """The run's PD term structure by rating grade (cumulative or marginal)."""
    from ..routes import analytics as A
    from ifrs9qdb.analytics import pd_curves_by_rating
    rid, bad = _run_or_fail(run_id, focus)
    if bad:
        return bad
    inp = A._inputs(rid)
    if inp is None:
        return _fail(f"Run {rid}'s PD curves could not be read.")
    c = pd_curves_by_rating(inp)
    sc = "External" if str(scale).lower().startswith("e") else "Internal"
    c = c[c["scale"] == sc]
    allr = list(dict.fromkeys(c["rating"]))
    want = [ratings] if isinstance(ratings, str) else list(ratings or [])
    if want:
        pick = [r for r in allr if any(str(w).strip().lower() == r.lower() for w in want)]
        if not pick:
            return _fail(f"No {sc} grade among {want}. Grades: {', '.join(allr)}")
    else:
        pick = allr[:: max(1, len(allr) // 5)][:6]
    yrs = max(1, min(int(years or 10), 50))
    c = c[c["rating"].isin(pick) & (c["month"] <= 12 * yrs)]
    col = "marginal_pd" if str(kind).lower().startswith("m") else "cum_pd"
    yearly = c[c["month"] % 12 == 0].assign(year=lambda x: x["month"] // 12)
    piv = yearly.pivot_table(index="year", columns="rating", values=col).reset_index()
    piv = piv[["year"] + [r for r in pick if r in piv.columns]]
    # the analytics give these curves in percent already
    long = c.assign(pd_pct=c[col])[["month", "rating", "pd_pct"]]
    return {"ok": True,
            "summary": f"{'Marginal' if col == 'marginal_pd' else 'Cumulative'} PD (%) by year, {sc} scale, run {rid}:\n{_text(piv)}",
            "table": _table(piv, f"{'Marginal' if col == 'marginal_pd' else 'Cumulative'} PD % by year · {sc} · {rid}"),
            "chart": {"kind": "line", "x": "month", "y": "pd_pct", "color": "rating",
                      "title": f"{'Cumulative' if col == 'cum_pd' else 'Marginal'} PD by month (%) · {sc} · {rid}",
                      "rows": long.to_dict(orient="records")}}


def concentration_(run_id=None, focus=None, **_) -> dict:
    from ..routes import analytics as A
    rid, bad = _run_or_fail(run_id, focus)
    if bad:
        return bad
    c = A.conc(rid, "customer")
    t = pd.DataFrame(c["top"]).head(15)
    return {"ok": True,
            "summary": (f"Concentration of the provision, run {rid}: index {c['hhi']:.0f} "
                        f"({c['band'].get('band')}), equivalent to {c['equivalent_customers']} equal customers.\n"
                        f"Largest contributors:\n{_text(t)}"),
            "table": _table(t, f"Largest contributors to ECL · {rid}")}


def data_quality(run_id=None, focus=None, **_) -> dict:
    from ..routes import analytics as A
    rid, bad = _run_or_fail(run_id, focus)
    if bad:
        return bad
    t = pd.DataFrame(A.quality(rid))
    return {"ok": True, "summary": f"Data-quality findings, run {rid}:\n{_text(t)}",
            "table": _table(t, f"Data quality · {rid}")}


def validation(run_id=None, only_failures: bool = True, focus=None, **_) -> dict:
    """The run's validation report: counts, and every check that did not pass
    with why it matters and the fix."""
    from ..routes import runs_detail as RD
    rid, bad = _run_or_fail(run_id, focus)
    if bad:
        return bad
    v = RD.run_validation(rid)
    if not v.get("exists"):
        return _fail(f"Run {rid} has no validation report.")
    t = pd.DataFrame(v["rows"])
    if only_failures and "status" in t:
        t = t[t["status"].astype(str).str.upper() != "PASS"]
    keep = [c for c in ("status", "id", "stage", "message", "rationale", "remediation") if c in t.columns]
    t = t[keep]
    c = v["counts"]
    return {"ok": True,
            "summary": (f"Validation of {rid}: {c.get('checks')} checks, {c.get('passed')} passed, "
                        f"{c.get('errors')} errors, {c.get('warnings')} warnings, {c.get('info')} info, "
                        f"{c.get('suppressed')} accepted.\n{_text(t, 30)}"),
            "table": _table(t, f"Checks not passed · {rid}")}


def run_info(run_id=None, focus=None, **_) -> dict:
    """Who ran it, when, with which config and calculator version, its
    approval status, overrides and overlays."""
    from ..routes import governance as G, runs_detail as RD
    rid, bad = _run_or_fail(run_id, focus)
    if bad:
        return bad
    m = (RD.run_manifest(rid) or {}).get("summary", {})
    keep = ["run_id", "portfolio_date", "run_type", "run_purpose", "user", "started_at",
            "finished_at", "config_version", "snapshot_status", "calculator_version", "ecl_scenario"]
    info = {k: m.get(k) for k in keep if k in m}
    try:
        st = G.run_status(rid)
        meta = st.get("meta") or {}
        info["approval_status"] = st.get("status")
        info["maker"] = st.get("maker")
        for t in meta.get("transitions") or []:
            if t.get("to") in ("approved", "rejected"):
                info[f"{t['to']}_by"] = t.get("by")
                info[f"{t['to']}_at"] = t.get("at")
                info["decision_reason"] = t.get("reason")
        ov = meta.get("overrides_applied")
        if isinstance(ov, dict):
            info["overrides"] = ", ".join(f"{k} {n}" for k, n in ov.items())
    except Exception:
        pass
    try:
        ap = G.applied_overlays(rid)
        names = [a.get("overlay_id") for a in (ap.get("applied") or ap.get("rows") or [])]
        info["overlays_applied"] = ", ".join(map(str, names)) or "none"
    except Exception:
        pass
    t = pd.DataFrame({"field": list(info), "value": [str(v) for v in info.values()]})
    return {"ok": True, "summary": f"Run {rid}:\n{_text(t)}", "table": _table(t, f"Run {rid}")}


def config_versions(**_) -> dict:
    from ..routes import governance as G
    s = G.snapshots()
    rows = s.get("snapshots") or s.get("rows") or []
    t = pd.DataFrame(rows)
    keep = [c for c in ("label", "status", "description", "created_by", "created_at", "base",
                        "tested_by", "approved_by") if c in t.columns]
    t = t[keep] if keep else t
    return {"ok": True, "summary": f"Config versions:\n{_text(t)}", "table": _table(t, "Config versions")}


def overlays(**_) -> dict:
    from ..routes import governance as G
    b = G.overlay_bundles()
    rows = []
    for o in b.get("bundles") or b.get("overlays") or []:
        tr = o.get("transitions") or []
        decided = next((t for t in reversed(tr) if t.get("to") in ("approved", "rejected")), {})
        rows.append({"overlay": o.get("id") or o.get("overlay_id"), "status": o.get("status"),
                     "rules": len(o.get("rules") or []), "approval_ref": o.get("approval_ref"),
                     "effective": o.get("effective_date"), "expiry": o.get("expiry"),
                     "maker": o.get("created_by"), "tested_by": o.get("tested_by"),
                     "decided_by": decided.get("by"), "decision_reason": decided.get("reason"),
                     "rules_detail": "; ".join(f"{r.get('method')} {r.get('level')}={r.get('target')} "
                                               f"{r.get('value')}: {r.get('comment') or r.get('reason')}"
                                               for r in (o.get("rules") or []))[:400]})
    t = pd.DataFrame(rows)
    return {"ok": True, "summary": f"Management overlays:\n{_text(t)}", "table": _table(t, "Overlays")}


def audit(run_id=None, n: int = 25, focus=None, **_) -> dict:
    from ..routes import governance as G
    rid, bad = _run_or_fail(run_id, focus)
    if bad:
        return bad
    rows = G.audit(rid)
    t = pd.DataFrame(rows).tail(int(n or 25))
    keep = [c for c in ("time", "timestamp", "ts", "who", "user", "action", "event", "detail", "reason")
            if c in t.columns]
    t = t[keep] if keep else t
    return {"ok": True, "summary": f"Audit trail of {rid} (latest {len(t)}):\n{_text(t)}",
            "table": _table(t, f"Audit trail · {rid}")}


def model(run_id=None, focus=None, **_) -> dict:
    """The PD model the run froze: macro variables with coefficient, weight,
    intercept and sd, the forecast, scenario severities and weights."""
    from ..routes import analytics as A
    rid, bad = _run_or_fail(run_id, focus)
    if bad:
        return bad
    mdl = A.model(rid)
    if not mdl.get("available"):
        return _fail(mdl.get("reason"))
    mev = pd.DataFrame(mdl["mev_weights"])
    fc = pd.DataFrame(mdl["mev_forecast"])
    sev = pd.DataFrame(mdl["severity"])
    used = mdl.get("weights_used") or {}
    w = pd.DataFrame({"scenario": list((used.get("internal") or {}).keys()),
                      "internal_%": [100 * v for v in (used.get("internal") or {}).values()],
                      "external_avg_%": [100 * (used.get("external") or {}).get(k, np.nan)
                                         for k in (used.get("internal") or {})]})
    import yaml
    from ifrs9qdb.analytics.model_view import config_used
    anchor = ""
    try:
        cu = config_used(A._run_output(rid))
        spec = yaml.safe_load((cu["config"] / "model.yml").read_text(encoding="utf-8")) or {}
        anchor = f"TTC anchor PD {spec.get('ttc_anchor_pd')}; horizons {spec.get('horizons')}."
    except Exception:
        pass
    return {"ok": True,
            "summary": (f"PD model frozen by run {rid}. {anchor}\nMacro variables (a zero weight means the "
                        f"variable does not move the PD):\n{_text(mev)}\n\nForecast:\n{_text(fc)}\n\n"
                        f"Scenario severities:\n{_text(sev)}\n\nScenario weights used:\n{_text(w)}"),
            "table": _table(mev, f"Macro model variables · {rid}"),
            "extra_tables": [_table(fc, f"Macro forecast · {rid}"), _table(w, f"Scenario weights used · {rid}")]}


def config_file(name="", run_id=None, focus=None, **_) -> dict:
    """A configuration file as a run froze it (or the live one): model.yml,
    model_inputs.yml, collateral_types.csv, staging_thresholds.csv,
    ttc_pd_table.csv, master_rating_scale.csv, ..."""
    from ..routes import analytics as A
    from ifrs9qdb.analytics.model_view import config_used
    want = str(name or "").strip().lower()
    if not want:
        return _fail("Name the file, e.g. collateral_types.csv or model_inputs.yml.")
    places = []
    rid, _ = resolve_run(run_id, focus)
    if rid:
        try:
            cu = config_used(A._run_output(rid))
            if cu:
                places += [(p, f"frozen by {rid}") for p in Path(cu["config"]).parent.rglob("*")
                           if p.is_file()]
        except Exception:
            pass
    places += [(Path(p), "live") for p, _l in K.config_files()]
    stem = want.rsplit(".", 1)[0]
    hit = next(((p, w) for p, w in places if p.name.lower() == want), None) or \
        next(((p, w) for p, w in places if stem and stem in p.name.lower()), None)
    if hit is None:
        names = sorted({p.name for p, _ in places if p.suffix in (".yml", ".yaml", ".csv")})
        return _fail(f"No config file {name!r}. Files: {', '.join(names[:40])}")
    p, where = hit
    if p.suffix == ".csv":
        df = pd.read_csv(p, comment="#")
        return {"ok": True, "summary": f"{p.name} ({where}):\n{_text(df, 60)}",
                "table": _table(df.head(200), f"{p.name} ({where})")}
    text = p.read_text(encoding="utf-8", errors="replace")
    return {"ok": True, "summary": f"{p.name} ({where}):\n{text[:5000]}"}


def search_docs(query="", scope="all", k: int = 5, **_) -> dict:
    """Search the user manual, the ECL and stress methodologies, the engine's
    code and the config files. Returns passages with citation ids."""
    if not str(query).strip():
        return _fail("Give search words.")
    hits = K.search(str(query), str(scope or "all"), max(1, min(int(k or 5), 8)))
    if not hits:
        return _fail(f"Nothing in the documents, code or config matches {query!r}.")
    parts = []
    for c in hits:
        body = c.text if c.kind != "code" else c.text[:1500]
        parts.append(f"[{c.id}] {K.cite_label(c)}\n{body[:1800]}")
    return {"ok": True, "summary": "\n\n".join(parts),
            "cites": [{"id": c.id, "label": K.cite_label(c), "kind": c.kind,
                       "where": c.where, "source": c.source, "section": c.section, "line": c.line}
                      for c in hits]}


def read_code(symbol="", **_) -> dict:
    """The engine's source for a function or class by name (or a citation id)."""
    c = K.chunk(symbol) if re.fullmatch(r"k\d+", str(symbol)) else K.code_symbol(symbol)
    if c is None:
        hits = K.search(str(symbol), "code", 5)
        return _fail(f"No function or class named {symbol!r}. Close matches: "
                     + ", ".join(f"{h.section} ({h.source})" for h in hits))
    return {"ok": True, "summary": f"[{c.id}] {K.cite_label(c)}\n```python\n{c.text[:5000]}\n```",
            "cites": [{"id": c.id, "label": K.cite_label(c), "kind": c.kind, "where": c.where,
                       "source": c.source, "section": c.section, "line": c.line}]}


TOOLS = {
    "runs": runs, "overview": overview, "breakdown": breakdown, "compare": compare,
    "movement": movement, "migration": migration, "top": top, "customer": customer,
    "staging": staging, "scenarios": scenarios, "pd_curve": pd_curve,
    "concentration": concentration_, "data_quality": data_quality,
    "validation": validation, "run_info": run_info, "config_versions": config_versions,
    "overlays": overlays, "audit": audit, "model": model, "config_file": config_file,
    "search_docs": search_docs, "read_code": read_code,
}

CATALOGUE = """\
DATA (run = an id like run_00002, "latest", "previous", a number, or a date like "Sep 2026"; omitted = the focus run)
- overview(run) — totals, ECL and coverage by stage and by portfolio, overlay. Start here for "how much / what is the provision".
- breakdown(run, by, measure, filters) — by: one or two of stage, portfolio, rating, rating_type, account_type, customer, maturity_band, dpd_band, watchlist, restructured. measure: ecl, exposure, ead, overlay, contracts, customers, coverage, pd12, pd, lgd. filters: {"stage": 2, "portfolio": "Off BS"}. Two dims (e.g. ["portfolio","stage"]) give a pivot.
- compare(run_a, run_b, by, measure, filters) — the same breakdown on two runs with change and %; run_a defaults to "previous", run_b to the focus run.
- movement(run_a, run_b, level, member) — WHY the ECL moved (derecognised, new business, exposure, stage, rating, macro, model, LGD, overlay). level: book (default), portfolio, stage, rating, account_type, customer; with no member a level gives one row per group.
- migration(run_a, run_b, kind) — customers moving between stages (kind=stage) or grades (kind=rating).
- top(run, by, measure, n, filters) — largest customers (by=customer) or contracts by ecl or exposure.
- customer(run, query) — one customer's contracts; query = id or part of the name.
- staging(run) — why contracts are in Stage 2 / Stage 3, DPD by stage.
- scenarios(run) — ECL under each macro scenario, the booked weighted ECL, scenario weights.
- pd_curve(run, ratings, scale, years, kind) — PD term structure; scale Internal or External; kind cumulative or marginal.
- concentration(run) · data_quality(run) · validation(run, only_failures)
GOVERNANCE
- runs() — every run with date, type, status, provision. run_info(run) — who, when, config and calculator version, approval, overrides, overlays.
- config_versions() · overlays() · audit(run, n)
MODEL AND CONFIG
- model(run) — PD model the run froze: macro variables with coefficient, weight, intercept, sd; forecast; severities; scenario weights used.
- config_file(name, run) — a config file as the run froze it: model.yml, model_inputs.yml, collateral_types.csv, staging_thresholds.csv, ttc_pd_table.csv, master_rating_scale.csv, product_portfolio_mapping.csv, fx_rates.csv …
KNOWLEDGE (for how/why/where questions; cite what you use)
- search_docs(query, scope) — search the user manual, ECL methodology, stress testing methodology (scope=docs), the engine code (scope=code), config (scope=config), or all. Returns passages with ids like k12.
- read_code(symbol) — the source of an engine function or class, e.g. read_code("compute_lgd")."""
