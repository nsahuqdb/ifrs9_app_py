"""What the scenario pages share: names, the builder's shapes, and the
charts of a scenario's paths and of the episode behind it.

A scenario sets a few *main* variables; the *linked effects* move the rest.
Main variables are drawn in plum, linked ones in teal, variables left at
baseline in grey -- on every chart, so the reading never changes.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import GREY, PLUM, TEAL

CAT = {"history": "History", "supervisory": "Supervisory", "hypothetical": "What-if",
       "current": "Current", "mine": "Saved"}
ROLE = {"main": "Set", "linked": "Linked", "off": "At baseline"}
ROLE_COLOUR = {"main": PLUM, "linked": TEAL, "off": GREY}
SHAPES = {"one_year": "One year", "recover": "Recovers", "held": "Held",
          "custom": "Year by year"}


def unit(u: str) -> str:
    return "pp" if u == "pp" else ("%" if u == "%" else u)


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
        self.ycols = [str(y) for y in years]
        self.vars = variables
        self.label = {k: v["label"] for k, v in variables.items()}
        self.var = {v: k for k, v in self.label.items()}
        self.cols = ["Variable", "Shape", "Size", "Over years"] + self.ycols
        self.shape_of = {v: k for k, v in SHAPES.items()}

    def _years(self, shape: str, size, n) -> list:
        return shape_path(self.shape_of.get(shape, "one_year"),
                          0.0 if _blank_num(size) else size, self.H,
                          2 if _blank_num(n) else int(n))

    def _frame(self, rows: list) -> pd.DataFrame:
        d = pd.DataFrame(rows, columns=self.cols)
        for c in ["Size", "Over years"] + self.ycols:
            d[c] = pd.to_numeric(d[c], errors="coerce").astype(float)
        return d

    def blank(self, v: str) -> dict:
        size = round(float(self.vars[v].get("sd") or 1.0), 1) * self.vars[v].get("adverse", -1)
        return {"Variable": self.label[v], "Shape": "One year", "Size": size,
                "Over years": 2, **dict(zip(self.ycols, self._years("One year", size, 2)))}

    def from_scenario(self, scn: dict) -> pd.DataFrame:
        rows = []
        shapes = scn.get("shapes") or {}
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
                         **dict(zip(self.ycols, p))})
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
                out.append(self.blank(v))                # a new row
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
        """The table as a scenario's main paths and builder shapes."""
        main, shapes = {}, {}
        for _, r in t.iterrows():
            v = self.var.get(r["Variable"])
            if v is None:
                continue
            main[v] = [None if _blank_num(r[y]) else float(r[y]) for y in self.ycols]
            shapes[v] = {"shape": self.shape_of.get(r["Shape"], "custom"),
                         "size": None if _blank_num(r["Size"]) else float(r["Size"]),
                         "years": 2 if _blank_num(r["Over years"]) else int(r["Over years"])}
        return main, shapes


def moves(v) -> str:
    """A yearly path in words: '-47.2, -15.0, +22.5'."""
    return ", ".join("·" if x is None else f"{x:+.1f}" for x in v)


def _grid(n: int, cols: int = 4):
    from plotly.subplots import make_subplots
    rows = (n + cols - 1) // cols
    return rows, cols, make_subplots


def path_grid(paths: list, height_per_row: int = 190) -> None:
    """Every variable's baseline (dashed) and scenario path over the
    forecast years, one small chart each, coloured by role."""
    import plotly.graph_objects as go
    d = pd.DataFrame(paths)
    if not len(d):
        return
    order = list(dict.fromkeys(d["variable"]))
    rows, cols, make_subplots = _grid(len(order))
    titles = []
    for v in order:
        g = d[d["variable"] == v]
        r = g.iloc[0]
        extra = "" if g["baseline"].notna().any() else ", change"
        titles.append(f"{r['label']} ({unit(r['unit'])}{extra})")
    fig = make_subplots(rows=rows, cols=cols, subplot_titles=titles,
                        horizontal_spacing=0.06, vertical_spacing=0.16)
    for i, v in enumerate(order):
        x = d[d["variable"] == v].sort_values("year")
        role = x["role"].iloc[0]
        rr, cc = i // cols + 1, i % cols + 1
        has_base = x["baseline"].notna().any()
        yb = x["baseline"] if has_base else [0.0] * len(x)
        ys = x["scenario"] if has_base else x["move"]
        fig.add_trace(go.Scatter(x=x["year"], y=yb, mode="lines",
                                 line=dict(color="#b7b0c2", width=1.6, dash="dash"),
                                 name="Baseline", showlegend=False,
                                 hovertemplate="%{x}: %{y:.1f}<extra>baseline</extra>"),
                      row=rr, col=cc)
        fig.add_trace(go.Scatter(x=x["year"], y=ys, mode="lines+markers",
                                 line=dict(color=ROLE_COLOUR.get(role, GREY), width=2.4),
                                 marker=dict(size=5), name=ROLE.get(role, role),
                                 showlegend=False,
                                 hovertemplate="%{x}: %{y:.1f}<extra>scenario</extra>"),
                      row=rr, col=cc)
        if "beyond_data" in x and x["beyond_data"].any():
            b = x[x["beyond_data"]]
            fig.add_trace(go.Scatter(x=b["year"], y=(b["scenario"] if has_base else b["move"]),
                                     mode="markers", marker=dict(size=10, symbol="circle-open",
                                                                 color="#d97706"),
                                     showlegend=False, hoverinfo="skip"), row=rr, col=cc)
    fig.update_layout(height=max(220, height_per_row * rows + 30),
                      margin=dict(l=6, r=6, t=34, b=6), plot_bgcolor="white",
                      paper_bgcolor="white", font=dict(size=11, color="#4a5162"))
    fig.update_xaxes(showgrid=False, tickformat="d", dtick=1)
    fig.update_yaxes(gridcolor="#f2eff6", zerolinecolor="#ded9e6")
    fig.update_annotations(font=dict(size=11.5, color="#2a2f3a"))
    st.plotly_chart(fig, use_container_width=True)


def history_grid(series: list, episode: list, height_per_row: int = 180) -> None:
    """How every variable moved through an episode: outturns solid, the
    episode's years shaded; the variables the scenario sets in plum."""
    import plotly.graph_objects as go
    d = pd.DataFrame(series)
    if not len(d):
        return
    # a variable with fewer than three years in the window says nothing
    n = d.groupby("variable")["year"].transform("count")
    d = d[n >= 3]
    if not len(d):
        return
    order = list(dict.fromkeys(d["variable"]))
    rows, cols, make_subplots = _grid(len(order))
    titles = []
    for v in order:
        r = d[d["variable"] == v].iloc[0]
        titles.append(f"{r['label']} ({unit(r['unit'])})")
    fig = make_subplots(rows=rows, cols=cols, subplot_titles=titles,
                        horizontal_spacing=0.06, vertical_spacing=0.16)
    e0, e1 = (episode or [None, None])[0], (episode or [None, None])[-1]
    for i, v in enumerate(order):
        x = d[d["variable"] == v].sort_values("year")
        rr, cc = i // cols + 1, i % cols + 1
        colour = PLUM if bool(x["set"].iloc[0]) else TEAL
        act = x[x["actual"]]
        fc = x[~x["actual"]]
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
    fig.update_layout(height=max(200, height_per_row * rows + 30),
                      margin=dict(l=6, r=6, t=34, b=6), plot_bgcolor="white",
                      paper_bgcolor="white", font=dict(size=11, color="#4a5162"))
    fig.update_xaxes(showgrid=False, tickformat="d")
    fig.update_yaxes(gridcolor="#f2eff6", zerolinecolor="#ded9e6")
    fig.update_annotations(font=dict(size=11.5, color="#2a2f3a"))
    st.plotly_chart(fig, use_container_width=True)


def path_table(paths: list, years: list, refs: dict | None = None) -> pd.DataFrame:
    """The paths as a table: one row per variable that moves, the change from
    baseline each year, main variables first."""
    d = pd.DataFrame(paths)
    if not len(d):
        return pd.DataFrame()
    rows = []
    for v, g in d.groupby("variable", sort=False):
        role = g["role"].iloc[0]
        if role == "off":
            continue
        g = g.set_index("year")
        r = {"Variable": g["label"].iloc[0], "Unit": unit(g["unit"].iloc[0]),
             "": ROLE[role]}
        for y in years:
            mv = float(g.loc[y, "move"])
            r[str(y)] = mv
        if refs is not None:
            how = refs.get(v, "linked effects" if role == "linked" else "")
            if role == "main" and "set" in g and not g["set"].all():
                how += ", then linked"
            r["How"] = how
        rows.append((0 if role == "main" else 1, r))
    rows.sort(key=lambda t: t[0])
    return pd.DataFrame([r for _, r in rows])


def show_path_table(paths: list, years: list, refs: dict | None = None) -> None:
    t = path_table(paths, years, refs)
    if not len(t):
        st.caption("Nothing moves.")
        return
    fmt = {str(y): "{:+.2f}" for y in years}
    st.dataframe(t.style.format(fmt), use_container_width=True, hide_index=True)
