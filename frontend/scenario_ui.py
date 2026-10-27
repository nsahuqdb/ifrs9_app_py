"""What the scenario pages share: names, the builder's shapes, and the
charts of a scenario's paths and of the episode behind it.

A scenario sets a few *main* variables; the *linked effects* move the rest.
Main variables are drawn in plum, linked ones in teal, variables not moved
in grey -- on every chart, so the reading never changes.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import GREY, PLUM, TEAL

CAT = {"history": "History", "supervisory": "Supervisory", "hypothetical": "What-if",
       "current": "Current", "mine": "Saved"}
REGION = {"global": "Global", "gcc": "GCC", "qatar": "Qatar"}
ROLE = {"main": "Set", "linked": "Linked", "off": "Not moved"}
YL = lambda j: f"Y{j}"                                   # noqa: E731

# The help beside each heading and control, in one place so the words
# agree across the pages.
HELP = {
    "shock": "A shock is how far the scenario moves a variable away from the run's own "
             "forecast for that year, in the variable's unit: points for growth rates and "
             "the policy rate, % for prices. Y1 is the first forecast year of whichever "
             "run the scenario is priced on, Y2 the next, and so on.",
    "set": "Set: the scenario gives this variable's value in that year. Linked: the value "
           "comes from the linked effects, the equations estimated on the macro data, "
           "and cannot be typed. Not moved: stays at the run's forecast.",
    "derivation": "How a historical shock is measured. Prices and the policy rate are "
                  "already changes, so the shock is the change recorded in the episode. "
                  "Growth rates are not normally zero, so the shock is the episode's growth "
                  "less the growth in the last year before the shock (the reference): it "
                  "keeps the size of the slowdown, not the level of growth at the time.",
    "history": "The recorded yearly values of every variable around the episode, from the "
               "macro store. The shaded years are the ones the scenario replays. Dotted: "
               "the IMF's projection, for years not yet recorded.",
    "why": "Each linked value is the sum of its drivers' parts: a driver's estimated "
           "effect times that driver's shock in the same year or the year before, plus "
           "the variable's own momentum from the year before. The parts add up to the "
           "value in the scenario.",
    "story": "What happened in the episode, from the sources listed, and how the scenario "
             "would unfold if it started in Y1.",
    "book": "The scenario reaches the provision through three channels: the PD models "
            "(non-oil growth for the internal book, GCC growth for the external book), "
            "stage moves, and property collateral.",
    "linked_pick": "The variables the main ones reach through the linked effects. Untick "
                   "one to leave it at the run's forecast: it then passes nothing on. To set a value "
                   "yourself, add the variable as a main variable instead.",
    "main_table": "One row per variable you set. Pick a shape and a size and the years "
                  "follow; or choose Year by year and type each year. A blank year is "
                  "filled by the linked effects.",
    "edit": "A library scenario is never changed: editing it opens a copy that is saved "
            "under a new name. A saved scenario keeps every version.",
    "captures": "What the scenario stands for: the event, episode or risk it captures and "
                "the evidence for its size, so a reviewer can judge it.",
    "narrative": "How the scenario unfolds from Y1: what starts it, how each main variable "
                 "moves year by year and why, and what follows from it.",
    "why_col": "Why this variable is set and how its numbers were sized: the episode, "
               "study or source behind them. Required for every main variable.",
    "book_txt": "Optional: which part of the book it should hit and through which channel "
                "(PD models, stage moves, property collateral).",
    "limits": "Optional: what to keep in mind when reading the result.",
    "sources": "The documents behind the scenario: a title and, where there is one, a link.",
    "region": "Where the shock starts: the world economy, the GCC, or Qatar itself.",
    "deferral": "The share of Stage 1 borrowers a payment-deferral programme moves to Stage 2 "
                "on top of the rating effect. In 2020 it was about 72% of QDB's.",
}
ROLE_COLOUR = {"main": PLUM, "linked": TEAL, "off": GREY}
SHAPES = {"one_year": "One year", "recover": "Recovers", "held": "Held",
          "custom": "Year by year"}


def unit(u: str) -> str:
    return "pp" if u == "pp" else ("%" if u == "%" else u)


def level_units(rows: list) -> dict:
    """The unit of each variable's value itself (not of a shock to it): a
    growth rate in %, a price as its % change, the policy rate as its change
    in points."""
    out = {}
    for r in rows:
        t = r.get("transform") or ""
        if "growth" in str(r.get("label", "")).lower():
            t = "none"
        out[r["variable"]] = {"none": "%", "pct_change": "% change",
                              "diff": "change, pp"}.get(t, unit(r.get("unit", "")))
    return out


def option(s: dict) -> str:
    """A scenario as a picker shows it."""
    return f"{CAT.get(s.get('category'), 'Saved')} · {s['name']}"


def shape_path(shape: str, size: float, H: int, years: int = 2) -> list:
    """The builder's shapes (the engine's stresstest.shape_path)."""
    size = float(size or 0.0)
    if shape == "held":
        return [size] * H
    if shape == "recover":
        n = max(1, int(years or 2))
        return [size * max(0.0, 1.0 - t / n) for t in range(min(n, H))] + [None] * max(0, H - n)
    return [size] + [None] * (H - 1)


def variables(rows: list) -> dict:
    """The setup's variables by name."""
    return {r["variable"]: r for r in rows}


def canon(df: pd.DataFrame) -> list:
    """A table's content, whatever its column types."""
    out = []
    for _, r in df.iterrows():
        row = []
        for c in df.columns:
            x = r[c]
            if x is None or (not isinstance(x, str) and pd.isna(x)):
                row.append(None)
                continue
            try:
                row.append(round(float(x), 9) if not isinstance(x, str) else x)
            except (TypeError, ValueError):
                row.append(str(x))
        out.append(tuple(row))
    return out


def _blank_num(x) -> bool:
    return x is None or (not isinstance(x, str) and pd.isna(x))


def _same(a, b) -> bool:
    if _blank_num(a) or _blank_num(b):
        return _blank_num(a) and _blank_num(b)
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return a == b


class MainTable:
    """The builder's table of main variables: one row each -- variable,
    shape, size, years to recover, and the move in each year.

    A changed shape, size or recovery redraws the years; a year typed in
    makes the row year by year (its size cleared); a size typed into a
    year-by-year row makes it a shape again; a new row starts as a
    one-standard-deviation adverse move in year 1."""

    def __init__(self, years: list, variables: dict):
        self.years = list(years)
        self.H = len(years)
        self.ycols = [f"Y{j + 1}" for j in range(self.H)]
        self.vars = variables
        self.label = {k: v["label"] for k, v in variables.items()}
        self.var = {v: k for k, v in self.label.items()}
        self.cols = ["Variable", "Shape", "Size", "Over years"] + self.ycols + ["Why"]
        self.shape_of = {v: k for k, v in SHAPES.items()}

    def _years(self, shape: str, size, n) -> list:
        return shape_path(self.shape_of.get(shape, "one_year"),
                          0.0 if _blank_num(size) else size, self.H,
                          2 if _blank_num(n) else int(n))

    def _frame(self, rows: list) -> pd.DataFrame:
        d = pd.DataFrame(rows, columns=self.cols)
        for c in ["Size", "Over years"] + self.ycols:
            d[c] = pd.to_numeric(d[c], errors="coerce").astype(float)
        d["Why"] = pd.Series([x if isinstance(x, str) else "" for x in d["Why"]],
                             index=d.index, dtype="object")
        for c in ("Variable", "Shape"):
            d[c] = d[c].astype("object")
        return d

    def blank(self, v: str) -> dict:
        size = round(float(self.vars[v].get("sd") or 1.0), 1) * self.vars[v].get("adverse", -1)
        return {"Variable": self.label[v], "Shape": "One year", "Size": size,
                "Over years": 2, **dict(zip(self.ycols, self._years("One year", size, 2))),
                "Why": ""}

    def from_scenario(self, scn: dict) -> pd.DataFrame:
        rows = []
        shapes = scn.get("shapes") or {}
        why = scn.get("why") or {}
        for v, p in (scn.get("main") or {}).items():
            if v not in self.vars or p is None or not any(x is not None for x in p):
                continue
            p = (list(p) + [None] * self.H)[:self.H]
            sh = shapes.get(v) or {}
            shape = SHAPES.get(sh.get("shape", "custom"), "Year by year")
            custom = shape == "Year by year"
            rows.append({"Variable": self.label[v], "Shape": shape,
                         "Size": None if custom else sh.get("size"),
                         "Over years": None if custom else int(sh.get("years", 2)),
                         **dict(zip(self.ycols, p)), "Why": why.get(v, "")})
        return self._frame(rows)

    def settle(self, new: pd.DataFrame, old: pd.DataFrame) -> tuple:
        """The table after an edit, and any variable entered twice."""
        out, seen, dup = [], set(), []
        old_by = {self.var.get(x["Variable"]): x for _, x in old.iterrows()}
        for _, r in new.reset_index(drop=True).iterrows():
            v = self.var.get(r.get("Variable"))
            if v is None:
                continue
            if v in seen:
                dup.append(v)
                continue
            seen.add(v)
            o = old_by.get(v)
            if o is None and not isinstance(r.get("Shape"), str):
                b = self.blank(v)                        # a new row
                if isinstance(r.get("Why"), str):
                    b["Why"] = r["Why"]
                out.append(b)
                continue
            r = r.to_dict()
            if not isinstance(r.get("Shape"), str):
                r["Shape"] = "One year"
            if o is None:                                # a row given another variable
                if r["Shape"] != "Year by year":
                    r.update(zip(self.ycols, self._years(r["Shape"], r["Size"],
                                                         r["Over years"])))
                out.append(r)
                continue
            years_ed = any(not _same(r[y], o[y]) for y in self.ycols)
            shape_ed = not _same(r["Shape"], o["Shape"])
            size_ed = not _same(r["Size"], o["Size"]) or not _same(r["Over years"],
                                                                  o["Over years"])
            if years_ed and not shape_ed and not size_ed:
                r["Shape"], r["Size"], r["Over years"] = "Year by year", None, None
            elif r["Shape"] == "Year by year" and size_ed and not shape_ed:
                r["Shape"] = "Recovers" if not _same(r["Over years"], o["Over years"]) \
                    else "One year"
            if r["Shape"] == "Year by year":
                r["Size"], r["Over years"] = None, None
            else:
                if _blank_num(r["Size"]):
                    r["Size"] = next((r[y] for y in self.ycols if not _blank_num(r[y])), 0.0)
                if _blank_num(r["Over years"]):
                    r["Over years"] = 2
                r.update(zip(self.ycols, self._years(r["Shape"], r["Size"], r["Over years"])))
            out.append(r)
        return self._frame(out), dup

    def to_main(self, t: pd.DataFrame) -> tuple:
        """The table as a scenario's main paths, builder shapes and the reason
        given for each variable."""
        main, shapes, why = {}, {}, {}
        for _, r in t.iterrows():
            v = self.var.get(r["Variable"])
            if v is None:
                continue
            why[v] = str(r.get("Why") or "").strip()
            main[v] = [None if _blank_num(r[y]) else float(r[y]) for y in self.ycols]
            shapes[v] = {"shape": self.shape_of.get(r["Shape"], "custom"),
                         "size": None if _blank_num(r["Size"]) else float(r["Size"]),
                         "years": 2 if _blank_num(r["Over years"]) else int(r["Over years"])}
        return main, shapes, why


def moves(v) -> str:
    """A yearly path in words: '-47.2, -15.0, +22.5'."""
    return ", ".join("·" if x is None else f"{x:+.1f}" for x in v)


def _grid(n: int, cols: int = 4):
    from plotly.subplots import make_subplots
    rows = (n + cols - 1) // cols
    return rows, cols, make_subplots


def _legend(fig, items: list) -> None:
    """Legend entries that stand for every small chart at once."""
    import plotly.graph_objects as go
    for name, colour, dash, mode in items:
        fig.add_trace(go.Scatter(x=[None], y=[None], mode=mode, name=name,
                                 line=dict(color=colour, width=2.4, dash=dash),
                                 marker=dict(size=6, color=colour), showlegend=True,
                                 hoverinfo="skip"), row=1, col=1)


def _layout(fig, rows: int, per_row: int) -> None:
    fig.update_layout(height=max(260, per_row * rows + 100),
                      margin=dict(l=6, r=6, t=64, b=6), plot_bgcolor="white",
                      paper_bgcolor="white", font=dict(size=11, color="#4a5162"),
                      legend=dict(orientation="h", yref="container", y=0.995, yanchor="top",
                                  x=0, xanchor="left", font=dict(size=11.5)))
    fig.update_yaxes(gridcolor="#f2eff6", zerolinecolor="#ded9e6")
    fig.update_annotations(font=dict(size=11.5, color="#2a2f3a"))


def path_grid(paths: list, height_per_row: int = 190) -> None:
    """Every variable's shock over Y1-Y5, one small chart each, coloured by
    role, with one legend for all."""
    import plotly.graph_objects as go
    d = pd.DataFrame(paths)
    if not len(d):
        return
    years = sorted(d["year"].unique())
    yi = {y: j + 1 for j, y in enumerate(years)}
    d = d.assign(t=d["year"].map(yi))
    order = list(dict.fromkeys(d["variable"]))
    rows, cols, make_subplots = _grid(len(order))
    titles = [f"{d[d['variable'] == v].iloc[0]['label']} "
              f"({unit(d[d['variable'] == v].iloc[0]['unit'])})" for v in order]
    fig = make_subplots(rows=rows, cols=cols, subplot_titles=titles,
                        horizontal_spacing=0.06, vertical_spacing=0.17)
    for i, v in enumerate(order):
        x = d[d["variable"] == v].sort_values("t")
        role = x["role"].iloc[0]
        rr, cc = i // cols + 1, i % cols + 1
        fig.add_hline(y=0, line=dict(color="#d9d4e0", width=1), row=rr, col=cc)
        fig.add_trace(go.Scatter(x=x["t"], y=x["move"], mode="lines+markers",
                                 line=dict(color=ROLE_COLOUR.get(role, GREY), width=2.4),
                                 marker=dict(size=6), showlegend=False,
                                 hovertemplate="Y%{x}: %{y:+.2f}<extra>" + ROLE.get(role, role)
                                 + "</extra>"), row=rr, col=cc)
        if "beyond_data" in x and x["beyond_data"].any():
            b = x[x["beyond_data"]]
            fig.add_trace(go.Scatter(x=b["t"], y=b["move"], mode="markers",
                                     marker=dict(size=11, symbol="circle-open", color="#d97706"),
                                     showlegend=False, hoverinfo="skip"), row=rr, col=cc)
    items = [("Set by the scenario", ROLE_COLOUR["main"], "solid", "lines+markers"),
             ("Linked effect", ROLE_COLOUR["linked"], "solid", "lines+markers")]
    if (d["role"] == "off").any():
        items.append(("Not moved", ROLE_COLOUR["off"], "solid", "lines+markers"))
    if "beyond_data" in d and d["beyond_data"].any():
        items.append(("Beyond the data the link was estimated on", "#d97706", "solid",
                      "markers"))
    _legend(fig, items)
    _layout(fig, rows, height_per_row)
    fig.update_xaxes(showgrid=False, tickmode="array", tickvals=list(yi.values()),
                     ticktext=[YL(j) for j in yi.values()])
    st.plotly_chart(fig, use_container_width=True)


def level_grid(paths: list, units: dict | None = None, height_per_row: int = 190) -> None:
    """On a run, where the calendar years are known: each moved variable's
    forecast in the macro data and its value under the scenario, side by
    side, one small chart each."""
    import plotly.graph_objects as go
    d = pd.DataFrame(paths)
    if not len(d) or "baseline" not in d:
        return
    moved = d[d["role"] != "off"]
    d = moved[moved["baseline"].notna()]
    none = [lb for v, lb in dict(zip(moved["variable"], moved["label"])).items()
            if v not in set(d["variable"])]
    if not len(d):
        return
    order = list(dict.fromkeys(d["variable"]))
    rows, cols, make_subplots = _grid(len(order))
    units = units or {}
    titles = [f"{d[d['variable'] == v].iloc[0]['label']} ({units.get(v, '%')})" for v in order]
    fig = make_subplots(rows=rows, cols=cols, subplot_titles=titles,
                        horizontal_spacing=0.06, vertical_spacing=0.17)
    for i, v in enumerate(order):
        x = d[d["variable"] == v].sort_values("year")
        role = x["role"].iloc[0]
        rr, cc = i // cols + 1, i % cols + 1
        fig.add_trace(go.Scatter(x=x["year"], y=x["baseline"], mode="lines+markers",
                                 line=dict(color="#b8b2c2", width=2), marker=dict(size=5),
                                 showlegend=False,
                                 hovertemplate="%{x}: %{y:.2f}<extra>forecast</extra>"),
                      row=rr, col=cc)
        fig.add_trace(go.Scatter(x=x["year"], y=x["scenario"], mode="lines+markers",
                                 line=dict(color=ROLE_COLOUR.get(role, GREY), width=2.4),
                                 marker=dict(size=6), showlegend=False,
                                 hovertemplate="%{x}: %{y:.2f}<extra>scenario</extra>"),
                      row=rr, col=cc)
    items = [("Forecast in the macro data", "#b8b2c2", "solid", "lines+markers"),
             ("Under the scenario: set", ROLE_COLOUR["main"], "solid", "lines+markers"),
             ("Under the scenario: linked", ROLE_COLOUR["linked"], "solid", "lines+markers")]
    _legend(fig, items)
    _layout(fig, rows, height_per_row)
    fig.update_xaxes(showgrid=False, tickformat="d", dtick=1)
    st.plotly_chart(fig, use_container_width=True)
    if none:
        st.caption(f"No forecast in the macro data for {'; '.join(none)}: "
                   "the shocks are in the table below.")


def history_grid(series: list, episode: list, units: dict | None = None,
                 height_per_row: int = 180) -> None:
    """How every variable moved through an episode, one small chart each:
    recorded values solid, projections dotted, the replayed years shaded;
    the variables the scenario sets in plum."""
    import plotly.graph_objects as go
    d = pd.DataFrame(series)
    if not len(d):
        return
    n = d.groupby("variable")["year"].transform("count")
    d = d[n >= 3]
    if not len(d):
        return
    order = list(dict.fromkeys(d["variable"]))
    rows, cols, make_subplots = _grid(len(order))
    units = units or {}
    titles = [f"{d[d['variable'] == v].iloc[0]['label']} ({units.get(v, '%')})" for v in order]
    fig = make_subplots(rows=rows, cols=cols, subplot_titles=titles,
                        horizontal_spacing=0.06, vertical_spacing=0.17)
    e0, e1 = (episode or [None, None])[0], (episode or [None, None])[-1]
    for i, v in enumerate(order):
        x = d[d["variable"] == v].sort_values("year")
        rr, cc = i // cols + 1, i % cols + 1
        colour = PLUM if bool(x["set"].iloc[0]) else TEAL
        act, fc = x[x["actual"]], x[~x["actual"]]
        fig.add_trace(go.Scatter(x=act["year"], y=act["value"], mode="lines+markers",
                                 line=dict(color=colour, width=2.2), marker=dict(size=4),
                                 showlegend=False,
                                 hovertemplate="%{x}: %{y:.1f}<extra></extra>"), row=rr, col=cc)
        if len(fc):
            j = pd.concat([act.tail(1), fc])
            fig.add_trace(go.Scatter(x=j["year"], y=j["value"], mode="lines",
                                     line=dict(color=colour, width=1.6, dash="dot"),
                                     showlegend=False, hovertemplate="%{x}: %{y:.1f}"
                                     "<extra>projection</extra>"), row=rr, col=cc)
        if e0 is not None:
            fig.add_vrect(x0=e0 - 0.5, x1=e1 + 0.5, fillcolor="#efe6f3", opacity=0.7,
                          line_width=0, layer="below", row=rr, col=cc)
    items = [("Recorded: set by the scenario", PLUM, "solid", "lines+markers"),
             ("Recorded: linked in the scenario", TEAL, "solid", "lines+markers")]
    if (~d["actual"]).any():
        items.append(("IMF projection", GREY, "dot", "lines"))
    _legend(fig, items)
    fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", name="Years replayed",
                             marker=dict(size=12, symbol="square", color="#efe6f3"),
                             showlegend=True, hoverinfo="skip"), row=1, col=1)
    _layout(fig, rows, height_per_row)
    fig.update_xaxes(showgrid=False, tickformat="d")
    st.plotly_chart(fig, use_container_width=True)


def _ycol(j: int, y, actual: bool) -> str:
    return f"{YL(j)} · {int(y)}" if actual else YL(j)


def path_table(paths: list, refs: dict | None = None, actual: bool = False) -> pd.DataFrame:
    """The shocks as a table: one row per variable that moves, Y1-Y5 (with
    the calendar year when ``actual``), main variables first."""
    d = pd.DataFrame(paths)
    if not len(d):
        return pd.DataFrame()
    years = sorted(d["year"].unique())
    rows = []
    for v, g in d.groupby("variable", sort=False):
        role = g["role"].iloc[0]
        if role == "off":
            continue
        g = g.set_index("year")
        r = {"Variable": g["label"].iloc[0], "Unit": unit(g["unit"].iloc[0]),
             "": ROLE[role]}
        for j, y in enumerate(years):
            r[_ycol(j + 1, y, actual)] = round(float(g.loc[y, "move"]), 2) + 0.0
        if refs is not None:
            how = refs.get(v, "linked effects" if role == "linked" else "")
            if role == "main" and "set" in g and not g["set"].all():
                how += "; blank years linked"
            r["How"] = how
        rows.append((0 if role == "main" else 1, r))
    rows.sort(key=lambda t: t[0])
    return pd.DataFrame([r for _, r in rows])


def show_path_table(paths: list, refs: dict | None = None, actual: bool = False) -> None:
    t = path_table(paths, refs, actual)
    if not len(t):
        st.caption("Nothing moves.")
        return
    ycols = [c for c in t.columns if c.startswith("Y") and c[1:].split(" ")[0].isdigit()]
    st.dataframe(t.style.format({c: "{:+.2f}" for c in ycols}), use_container_width=True,
                 hide_index=True)


def explain_tables(explain: list, paths: list, about: dict) -> None:
    """Why each filled value is what it is: for each variable the linked
    effects moved, its drivers' parts by year, and their total. A year the
    scenario sets itself reads 'set'."""
    e = pd.DataFrame(explain)
    if not len(e):
        st.caption("No variable is moved by the linked effects.")
        return
    p = pd.DataFrame(paths)
    label = dict(zip(p["variable"], p["label"]))
    uni = dict(zip(p["variable"], p["unit"]))
    years = sorted(p["year"].unique())
    H = len(years)
    for v in dict.fromkeys(p["variable"]):
        g = e[e["variable"] == v]
        if not len(g):
            continue
        pv = p[p["variable"] == v].sort_values("year")
        is_set = [bool(x) for x in (pv["set"] if "set" in pv else [False] * H)]
        g = g.assign(driver_txt=[f"{lb}{' (year before)' if lag and d != v else ''}"
                                 for lb, lag, d in zip(g["driver_label"], g["lag"], g["driver"])])
        t = g.pivot_table(index="driver_txt", columns="year", values="part", aggfunc="sum")
        t = t.reindex(columns=range(1, H + 1)).astype(float)
        t = t.loc[t.abs().sum(axis=1).sort_values(ascending=False).index]
        t.loc["Total"] = t.sum(axis=0, min_count=1)
        out = pd.DataFrame({"Driver": list(t.index)})
        for j in range(1, H + 1):
            col = t[j].tolist()
            if j <= len(is_set) and is_set[j - 1]:
                out[YL(j)] = [""] * (len(col) - 1) + ["set"]
            else:
                out[YL(j)] = ["" if pd.isna(x) else f"{round(x, 2) + 0.0:+.2f}" for x in col]
        st.markdown(f"**{label.get(v, v)}** ({unit(uni.get(v, ''))})", help=about.get(v) or None)
        cfg = {YL(j): st.column_config.TextColumn(alignment="right") for j in range(1, H + 1)}
        st.dataframe(out, use_container_width=True, hide_index=True, column_config=cfg)
