"""What the scenario pages share: names, the builder's table, and the
charts and tables of a scenario -- its shocks, the episode behind it, and
how the shock travels from the main variables to the rest.

A scenario sets a few *main* variables; the *linked effects* move the rest.
Main variables are drawn in plum, linked ones in teal, on every chart, so
the reading never changes.
"""
from __future__ import annotations

import html as _html

import pandas as pd
import streamlit as st

from ui import GREY, PLUM, TEAL

CAT = {"history": "History", "supervisory": "Supervisory", "hypothetical": "What-if",
       "current": "Current", "mine": "Own"}
REGION = {"global": "Global", "gcc": "GCC", "qatar": "Qatar"}
ROLE = {"main": "Set", "linked": "Linked", "off": "Not moved"}
YL = lambda j: f"Y{j}"                                   # noqa: E731
WHY = "Rationale"

# The list on the library page, in this order.
GROUPS = {"global": "Global events", "gcc": "GCC and Qatar", "supervisory": "Supervisory",
          "whatif": "What-if", "saved": "Saved"}


def group_of(s: dict) -> str:
    """Where a scenario sits in the library's list."""
    if s.get("category") == "supervisory":
        return "supervisory"
    if s.get("saved") or s.get("category") == "mine":
        return "saved"
    if s.get("category") == "hypothetical":
        return "whatif"
    return "global" if s.get("region") == "global" else "gcc"


def first_heading(s: dict) -> str:
    """The first heading of a scenario's description: what it stands for."""
    c = s.get("category")
    if c in ("history", "current"):
        return "Historical event"
    if c == "supervisory":
        return "Published scenario"
    return "Basis"


# The help beside each heading and control, in one place so the words
# agree across the pages.
HELP = {
    "shock": "A shock is how far the scenario moves a variable away from the run's own "
             "forecast for that year, in the variable's unit: points for growth rates and "
             "the policy rate, % for prices. Y1 is the first forecast year of whichever "
             "run the scenario is priced on, Y2 the next, and so on.",
    "set": "Set: the scenario gives this variable's value in that year. Linked: the value "
           "comes from the linked effects, the equations estimated on the macro data, "
           "and cannot be typed.",
    "derivation": "How a historical value is measured. Prices and the policy rate are "
                  "already changes, so the value is the change recorded in the episode. "
                  "Growth rates are not normally zero, so the value is the episode's growth "
                  "less the growth in the last year before the shock: it keeps the size of "
                  "the slowdown, not the level of growth at the time.",
    "history": "The recorded yearly values of every variable around the episode, from the "
               "macro store, Qatar's real GDP included. The shaded years are the ones the "
               "scenario replays. Dotted: the IMF's projection, for years not yet recorded.",
    "event": "The event the scenario replays, from the sources listed.",
    "published": "The supervisor's scenario that this one translates.",
    "basis": "What the scenario stands for and the evidence for its size.",
    "narrative": "How the scenario unfolds from Y1: what starts it, how each variable moves "
                 "year by year and why, and what follows from it.",
    "variables_set": "The variables the scenario sets, their values and the basis for them. "
                     "Every other variable follows through the linked effects.",
    "translation": "A supervisor's variables are not all ours; this is how they were mapped "
                   "onto the variables here.",
    "provision": "The scenario reaches the provision through three channels: the PD models "
                 "(through the variables each model reads, as model.yml gives them), stage "
                 "moves, and property collateral.",
    "limits": "What to keep in mind when reading the result.",
    "sources": "The documents behind the scenario: a title and, where there is one, a link.",
    "transmission": "How the main variables move the others. Each arrow points from a driver "
                    "to a variable it moves, with the share of that variable's movement over "
                    "Y1-Y5 that comes from it; channels under 15% are left out of the graph "
                    "and named in the sentences below. Plum: set by the scenario; teal: moved "
                    "by the linked effects, the equations estimated on the macro data.",
    "explained": "Each bar adds up the drivers' parts of the variable's move in that year: "
                 "a driver's estimated effect times the driver's own move, the same year or "
                 "the year before, plus the variable's momentum from the year before. The "
                 "parts add up to the dot.",
    "linked_pick": "The variables the main ones reach through the linked effects. Untick "
                   "one to leave it at the run's forecast: it then passes nothing on. To set "
                   "a value yourself, add the variable as a main variable instead.",
    "main_table": "One row per variable you set. Pick a shape and a size and the years "
                  "follow; or choose Year by year and type each year. A blank year is "
                  "filled by the linked effects.",
    "edit": "A library scenario is never changed: editing it opens a copy that is saved "
            "under a new name. A saved scenario keeps every version.",
    "rationale": "Why this variable is set and how its values were sized: the episode, "
                 "study or publication behind them. Required for every main variable.",
    "book_txt": "Optional: which part of the book it should hit and through which channel "
                "(PD models, stage moves, property collateral).",
    "region": "Where the shock starts: the world economy, the GCC, or Qatar itself.",
    "type": "Own: a scenario of your own, listed under Saved. Supervisory: a scenario a "
            "supervisor published (the Fed, the ESRB or EBA, QCB), entered from its "
            "publication and listed under Supervisory.",
    "source": "Who published it, or what it is built on.",
    "deferral": "The share of Stage 1 borrowers a payment-deferral programme moves to Stage 2 "
                "on top of the rating effect. In 2020 it was about 72% of QDB's.",
    "fed": "The Federal Reserve publishes its stress test scenarios every February as four "
           "tables: a baseline and a severely adverse scenario, each domestic and "
           "international. The severely adverse scenario less the baseline gives world GDP "
           "growth (regions weighted by their shares of world output) and the US rate; "
           "everything else follows through the linked effects.",
}
ROLE_COLOUR = {"main": PLUM, "linked": TEAL, "off": GREY}
SHAPES = {"one_year": "One year", "recover": "Recovers", "held": "Held",
          "custom": "Year by year"}
# Drivers in the transmission charts: a fixed colour each (validated for
# colour-blind separation), and a light grey for a variable's own momentum.
DRIVER_COLOUR = {"GDP_WLD": "#2a78d6", "OIL_PRICE": "#eb6834", "US_RATE": "#1baf7a",
                 "GOV_SPEND_QAT": "#eda100", "NONOIL_GDP_QAT": "#e87ba4",
                 "CREDIT_QAT": "#008300", "GDP_QAT": "#6250d6", "PROPERTY_QAT": "#6250d6",
                 "GDP_GCC": "#6250d6", "_momentum": "#c3bfcc", "_set": "#dccbe6"}

CSS = """
<style>
.scn-table {width:100%; border-collapse:separate; border-spacing:0; font-size:.86rem;
  background:#fff; border:1px solid var(--line); border-radius:10px; overflow:hidden;
  margin:.15rem 0 .4rem;}
.scn-table th {font-weight:600; color:var(--muted); font-size:.76rem; padding:.5rem .7rem;
  background:#faf8fc; border-bottom:1px solid var(--line); text-align:left; white-space:nowrap;}
.scn-table td {padding:.45rem .7rem; border-bottom:1px solid #f1eef5; color:var(--ink);
  vertical-align:middle;}
.scn-table tr:last-child td {border-bottom:none;}
.scn-table th.num, .scn-table td.num {text-align:right; font-variant-numeric:tabular-nums;
  white-space:nowrap;}
.scn-table td.muted {color:var(--faint);}
.scn-table td.note {color:var(--ink-2); font-size:.82rem;}
.chip {display:inline-block; padding:0 7px; border-radius:999px; font-size:.7rem; line-height:1.35rem;
  font-weight:600; border:1px solid transparent; white-space:nowrap;}
.chip-set {background:var(--plum-100); color:var(--plum); border-color:var(--plum-200);}
.chip-linked {background:#e6f6f4; color:#0f766e; border-color:#b7e4de;}
.scn-sec {font-size:.8rem; font-weight:700; letter-spacing:.04em; text-transform:uppercase;
  color:var(--muted); margin:.9rem 0 .2rem;}
.scn-text {color:var(--ink-2); line-height:1.6; font-size:.92rem; margin:0 0 .9rem;}
.scn-var {display:flex; gap:.6rem; align-items:baseline; padding:.35rem 0;
  border-bottom:1px solid #f1eef5;}
.scn-var:last-child {border-bottom:none; margin-bottom:.8rem;}
.scn-var .nm {font-weight:600; color:var(--ink); min-width:13rem;}
.scn-var .vals {font-variant-numeric:tabular-nums; color:var(--plum); min-width:11rem;
  white-space:nowrap;}
.scn-var .why {color:var(--ink-2); font-size:.88rem;}
.scn-say {color:var(--ink-2); font-size:.88rem; line-height:1.55; margin:.1rem 0 .2rem;}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def esc(x) -> str:
    return _html.escape("" if x is None else str(x))


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
    return f"{CAT.get(s.get('category'), 'Own')} · {s['name']}"


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
        self.cols = ["Variable", "Shape", "Size", "Over years"] + self.ycols + [WHY]
        self.shape_of = {v: k for k, v in SHAPES.items()}

    def _years(self, shape: str, size, n) -> list:
        return shape_path(self.shape_of.get(shape, "one_year"),
                          0.0 if _blank_num(size) else size, self.H,
                          2 if _blank_num(n) else int(n))

    def _frame(self, rows: list) -> pd.DataFrame:
        d = pd.DataFrame(rows, columns=self.cols)
        for c in ["Size", "Over years"] + self.ycols:
            d[c] = pd.to_numeric(d[c], errors="coerce").astype(float)
        d[WHY] = pd.Series([x if isinstance(x, str) else "" for x in d[WHY]],
                             index=d.index, dtype="object")
        for c in ("Variable", "Shape"):
            d[c] = d[c].astype("object")
        return d

    def blank(self, v: str) -> dict:
        size = round(float(self.vars[v].get("sd") or 1.0), 1) * self.vars[v].get("adverse", -1)
        return {"Variable": self.label[v], "Shape": "One year", "Size": size,
                "Over years": 2, **dict(zip(self.ycols, self._years("One year", size, 2))),
                WHY: ""}

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
                         **dict(zip(self.ycols, p)), WHY: why.get(v, "")})
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
                if isinstance(r.get(WHY), str):
                    b[WHY] = r[WHY]
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
            why[v] = str(r.get(WHY) or "").strip()
            main[v] = [None if _blank_num(r[y]) else float(r[y]) for y in self.ycols]
            shapes[v] = {"shape": self.shape_of.get(r["Shape"], "custom"),
                         "size": None if _blank_num(r["Size"]) else float(r["Size"]),
                         "years": 2 if _blank_num(r["Over years"]) else int(r["Over years"])}
        return main, shapes, why




def moves(v) -> str:
    """A yearly path in words: '-47.2, -15.0, +22.5'."""
    return ", ".join("·" if x is None else f"{x:+.1f}" for x in v)


def num(x, dp: int = 2) -> str:
    """A signed figure, with a true minus sign; '' for a blank."""
    if x is None or (not isinstance(x, str) and pd.isna(x)):
        return ""
    v = round(float(x), dp) + 0.0
    return f"{v:+.{dp}f}".replace("-", "−")


# ------------------------------------------------------------------ tables --
def html_table(cols: list, rows: list) -> None:
    """A table drawn in HTML so its headers align with its figures.
    ``cols``: [(key, label, "num" | "text" | "note" | "raw")]; ``rows``:
    dicts of values (strings, already formatted for "num")."""
    head = "".join(f'<th class="{"num" if k == "num" else ""}">{esc(lb)}</th>'
                   for _, lb, k in cols)
    body = []
    for r in rows:
        cells = []
        for key, _, kind in cols:
            v = r.get(key, "")
            if kind == "raw":
                cells.append(f"<td>{v}</td>")
            elif kind == "num":
                cells.append(f'<td class="num">{esc(v)}</td>')
            elif kind == "note":
                cells.append(f'<td class="note">{esc(v)}</td>')
            else:
                cells.append(f"<td>{esc(v)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    st.markdown(f'<table class="scn-table"><thead><tr>{head}</tr></thead><tbody>'
                + "".join(body) + "</tbody></table>", unsafe_allow_html=True)


def chip(role: str) -> str:
    return (f'<span class="chip chip-{"set" if role == "main" else "linked"}">'
            f'{ROLE.get(role, role)}</span>')


def moved(paths: list) -> pd.DataFrame:
    """The rows of the variables a scenario moves, in the system's order."""
    d = pd.DataFrame(paths)
    if not len(d):
        return d
    keep = [v for v, g in d.groupby("variable", sort=False)
            if g["role"].iloc[0] != "off" and g["move"].abs().max() > 1e-9]
    return d[d["variable"].isin(keep)]


def shock_table(paths: list, refs: dict | None = None, actual: bool = False) -> None:
    """The shocks as a table: one row per variable the scenario moves, main
    variables first, the years across, and how each was set."""
    d = moved(paths)
    if not len(d):
        st.caption("Nothing moves.")
        return
    years = sorted(d["year"].unique())
    ycols = [(f"y{j}", f"{YL(j + 1)} · {int(y)}" if actual else YL(j + 1), "num")
             for j, y in enumerate(years)]
    rows = []
    for v, g in d.groupby("variable", sort=False):
        role = g["role"].iloc[0]
        g = g.set_index("year")
        r = {"var": g["label"].iloc[0], "role": chip(role), "unit": unit(g["unit"].iloc[0])}
        for j, y in enumerate(years):
            r[f"y{j}"] = num(g.loc[y, "move"])
        if refs is not None:
            how = refs.get(v, "linked effects" if role == "linked" else "")
            if role == "main" and "set" in g and not g["set"].all():
                how += "; blank years linked"
            r["how"] = how
        rows.append((0 if role == "main" else 1, r))
    rows.sort(key=lambda t: t[0])
    cols = [("var", "Variable", "text"), ("role", "", "raw"), ("unit", "Unit", "text")] + ycols
    if refs is not None:
        cols.append(("how", "Basis", "note"))
    html_table(cols, [r for _, r in rows])


def show_path_table(paths: list, refs: dict | None = None, actual: bool = False) -> None:
    shock_table(paths, refs, actual)


def derivation_table(rows: list) -> None:
    """How each value of a library scenario was derived from the data."""
    d = pd.DataFrame(rows)
    if not len(d):
        return
    out = []
    for _, r in d.iterrows():
        u = unit(r["unit"])
        if r["rule"] == "source":
            how = "from the publication"
        elif r["rule"] == "then":
            how = "held at the new level"
        elif r["rule"] == "actual":
            what = "IMF projection for" if r.get("projected") else "recorded change in"
            how = f"{what} {int(r['year'])}: {num(r['recorded'])}{'%' if u == '%' else ''}"
        else:
            how = (f"{num(r['recorded'])} in {int(r['year'])} less "
                   f"{num(r['reference'])} in {int(r['reference_year'])}"
                   + (" (IMF projection)" if r.get("projected") else ""))
        out.append({"var": r["label"], "y": YL(int(r["y"])), "val": num(r["shock"]),
                    "unit": u, "how": how})
    html_table([("var", "Variable", "text"), ("y", "Year", "text"), ("val", "Value", "num"),
                ("unit", "Unit", "text"), ("how", "Derived as", "note")], out)


# ------------------------------------------------------------------ charts --
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
                                 marker=dict(size=8, color=colour), showlegend=True,
                                 hoverinfo="skip"), row=1, col=1)


def _layout(fig, rows: int, per_row: int) -> None:
    fig.update_layout(height=max(260, per_row * rows + 100),
                      margin=dict(l=6, r=6, t=64, b=6), plot_bgcolor="white",
                      paper_bgcolor="white", font=dict(size=11, color="#4a5162"),
                      legend=dict(orientation="h", yref="container", y=0.995, yanchor="top",
                                  x=0, xanchor="left", font=dict(size=11.5)))
    fig.update_yaxes(gridcolor="#f2eff6", zerolinecolor="#ded9e6")
    fig.update_annotations(font=dict(size=11.5, color="#2a2f3a"))


def shock_grid(paths: list, height_per_row: int = 190) -> None:
    """Each moved variable's shock over Y1-Y5, one small chart each,
    coloured by role, with one legend for all. Variables the scenario does
    not move are left out."""
    import plotly.graph_objects as go
    d = moved(paths)
    if not len(d):
        return
    years = sorted(d["year"].unique())
    yi = {y: j + 1 for j, y in enumerate(years)}
    d = d.assign(t=d["year"].map(yi))
    order = list(dict.fromkeys(d["variable"]))
    cols = 4 if len(order) > 4 else max(len(order), 2)
    rows, cols, make_subplots = _grid(len(order), cols)
    titles = [f"{d[d['variable'] == v].iloc[0]['label']} "
              f"({unit(d[d['variable'] == v].iloc[0]['unit'])})" for v in order]
    fig = make_subplots(rows=rows, cols=cols, subplot_titles=titles,
                        horizontal_spacing=0.06, vertical_spacing=0.17)
    for i, v in enumerate(order):
        x = d[d["variable"] == v].sort_values("t")
        role = x["role"].iloc[0]
        rr, cc = i // cols + 1, i % cols + 1
        fig.add_hline(y=0, line=dict(color="#d9d4e0", width=1), row=rr, col=cc)
        mc = ([PLUM if bool(z) else TEAL for z in x["set"]]
              if role == "main" and "set" in x else ROLE_COLOUR.get(role, GREY))
        fig.add_trace(go.Scatter(x=x["t"], y=x["move"], mode="lines+markers",
                                 line=dict(color=ROLE_COLOUR.get(role, GREY), width=2.2),
                                 marker=dict(size=8, color=mc), showlegend=False,
                                 hovertemplate="Y%{x}: %{y:+.2f}<extra>" + ROLE.get(role, role)
                                 + "</extra>"), row=rr, col=cc)
        if "beyond_data" in x and x["beyond_data"].any():
            b = x[x["beyond_data"]]
            fig.add_trace(go.Scatter(x=b["t"], y=b["move"], mode="markers",
                                     marker=dict(size=13, symbol="circle-open", color="#d97706"),
                                     showlegend=False, hoverinfo="skip"), row=rr, col=cc)
    items = [("Set by the scenario", ROLE_COLOUR["main"], "solid", "lines+markers")]
    if (d["role"] == "linked").any() or ("set" in d and not d["set"].all()):
        items.append(("Linked effect", ROLE_COLOUR["linked"], "solid", "lines+markers"))
    if "beyond_data" in d and d["beyond_data"].any():
        items.append(("Beyond the data the link was estimated on", "#d97706", "solid",
                      "markers"))
    _legend(fig, items)
    _layout(fig, rows, height_per_row)
    fig.update_xaxes(showgrid=False, tickmode="array", tickvals=list(yi.values()),
                     ticktext=[YL(j) for j in yi.values()])
    st.plotly_chart(fig, use_container_width=True)


path_grid = shock_grid


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




# ------------------------------------------------------------ transmission --
_KEEP_CASE = ("US", "GCC", "Qatar")


_THE = ("OIL_PRICE", "US_RATE")


def _nice(label: str, var: str | None = None) -> str:
    """A label inside a sentence: lower case unless it starts with a name,
    with 'the' before a price or a rate."""
    t = label if label.startswith(_KEEP_CASE) else label[:1].lower() + label[1:]
    return ("the " + t) if var in _THE else t


def _coef(c: float) -> str:
    a = abs(c)
    s = f"{c:+.3f}" if a < 0.1 else (f"{c:+.2f}" if a < 10 else f"{c:+.1f}")
    return s.replace("-", "−")


def _join(xs: list) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def _shares(e: pd.DataFrame, v: str) -> pd.Series:
    """Each driver's share of a variable's linked movement over Y1-Y5 (its
    parts' absolute sizes); a variable's own lag is its momentum."""
    g = e[e["variable"] == v]
    if not len(g):
        return pd.Series(dtype=float)
    key = g["driver"].where(g["driver"] != v, "_momentum")
    a = g["part"].abs().groupby(key).sum()
    return (a / a.sum()).sort_values(ascending=False) if a.sum() > 0 else a


def _moves_text(p: list, u: str) -> str:
    m = max((abs(x) for x in p), default=0.0)
    idx = [j for j, x in enumerate(p) if abs(x) >= max(0.05, 0.15 * m)]
    idx = sorted(sorted(idx, key=lambda j: -abs(p[j]))[:3])
    if not idx:
        return ""
    unit_w = " points" if u == "pp" else "%"
    parts = [f"{num(p[j], 1)}{unit_w if k == 0 else ('' if u == 'pp' else '%')} in {YL(j + 1)}"
             for k, j in enumerate(idx)]
    return "Moves " + _join(parts) + "."


def sentence(v: str, label: str, u: str, p: list, set_: list, e: pd.DataFrame,
             links: pd.DataFrame, labels: dict) -> str:
    """One variable's move in plain words: how much, from where, and the
    estimated link behind its largest driver."""
    out = []
    sy = [j for j, s in enumerate(set_) if s]
    if sy:
        span = YL(sy[0] + 1) if len(sy) == 1 else f"{YL(sy[0] + 1)}-{YL(sy[-1] + 1)}"
        lk = [j for j in range(len(p)) if j not in sy]
        lspan = (YL(lk[0] + 1) if len(lk) == 1 else f"{YL(lk[0] + 1)}-{YL(lk[-1] + 1)}"
                 if lk else "")
        out.append(f"Set by the scenario in {span}"
                   + (f"; in {lspan} it follows the linked effects." if lk else "."))
        mt = _moves_text([0.0 if j in sy else x for j, x in enumerate(p)], u)
    else:
        mt = _moves_text(p, u)
    if mt:
        out.append(mt)
    sh = _shares(e, v)
    if len(sh):
        name = lambda k: ("its own momentum" if k == "_momentum"           # noqa: E731
                          else _nice(labels.get(k, k), k))
        top = [k for k, x in sh.items() if x >= 0.12][:3] or [sh.index[0]]
        if sh.iloc[0] >= 0.6 and (len(sh) == 1 or sh.iloc[1] < 0.15):
            out.append(f"Mostly from {name(sh.index[0])} ({sh.iloc[0]:.0%}).")
        else:
            out.append("From " + _join([f"{name(k)} ({sh[k]:.0%})" for k in top]) + ".")
        lead = next((k for k in sh.index if k != "_momentum"), None)
        if lead is not None and len(links):
            lk = links[(links["variable"] == v) & (links["driver"] == lead)
                       & (links["coef"].abs() > 1e-6)].sort_values("lag")
            used = set(e[(e["variable"] == v) & (e["driver"] == lead)]["lag"])
            lk = lk[lk["lag"].isin(used)]
            if len(lk):
                du = lk["driver_unit"].iloc[0]
                per = (f"for each 1% change in {_nice(labels.get(lead, lead), lead)}"
                       if du == "%" else
                       f"for each point of {_nice(labels.get(lead, lead), lead)}")
                tw = " points" if u == "pp" else "%"
                when = [f"{_coef(r.coef)}{tw if i == 0 else ''} "
                        f"{'the same year' if r.lag == 0 else 'the year after'}"
                        for i, r in enumerate(lk.itertuples())]
                out.append(f"Estimated on the macro data: it moves {_join(when)} {per}.")
        own = links[(links["variable"] == v) & (links["driver"] == v)] if len(links) else []
        if len(own) and abs(float(own["coef"].iloc[0])) > 0.01 and "_momentum" in sh.index:
            out.append(f"It carries {float(own['coef'].iloc[0]):.0%} of last year's move "
                       "into the next.")
    return " ".join(out)


def _graph(d: pd.DataFrame, e: pd.DataFrame) -> str:
    """The transmission graph in DOT: moved variables as boxes (set in
    plum, linked in teal), an arrow from each driver to each variable it
    moves, labelled with its share of that variable's movement."""
    lines = ['digraph G {', 'rankdir=LR; bgcolor="transparent"; nodesep=0.3; ranksep=0.7;',
             'node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, '
             'margin="0.2,0.09", penwidth=1.4];',
             'edge [fontname="Helvetica", fontsize=10, color="#9aa3b2", fontcolor="#344054", '
             'arrowsize=0.7];']
    present = list(dict.fromkeys(d["variable"]))
    for v in present:
        g = d[d["variable"] == v].sort_values("year")
        role = g["role"].iloc[0]
        p = g["move"].tolist()
        j = max(range(len(p)), key=lambda k: abs(p[k]))
        u = unit(g["unit"].iloc[0])
        val = f"{num(p[j], 1)}{' pts' if u == 'pp' else '%'} in {YL(j + 1)}"
        lab = (f'<<b>{esc(g["label"].iloc[0])}</b><br/>'
               f'<font point-size="10">{esc(val)}</font>>')
        if role == "main":
            st_ = 'fillcolor="#5b1f6e", color="#5b1f6e", fontcolor="white"'
        else:
            st_ = 'fillcolor="#e9f7f5", color="#0d9488", fontcolor="#1f2430"'
        lines.append(f'"{v}" [label={lab}, {st_}];')
    src = [v for v in present if (d[d["variable"] == v]["role"] == "main").all()
           and not (e["variable"] == v).any()]
    if src:
        lines.append("{rank=source; " + " ".join(f'"{v}";' for v in src) + "}")
    for v in present:
        sh = _shares(e, v)
        for k, x in sh.items():
            # the main channels only; smaller shares are in the sentences
            if k == "_momentum" or k not in present or x < 0.15:
                continue
            w = 0.8 + 3.2 * float(x)
            lines.append(f'"{k}" -> "{v}" [label=" {x:.0%} ", penwidth={w:.1f}];')
    lines.append("}")
    return "\n".join(lines)


def _bars(v: str, g: pd.DataFrame, e: pd.DataFrame, labels: dict, H: int) -> None:
    """A variable's move each year split into its drivers' parts."""
    import plotly.graph_objects as go
    ev = e[e["variable"] == v]
    xs = [YL(j) for j in range(1, H + 1)]
    fig = go.Figure()
    set_ = [bool(s) for s in g["set"]] if "set" in g else [False] * H
    p = g["move"].tolist()
    if any(set_):
        fig.add_trace(go.Bar(x=xs, y=[p[j] if set_[j] else 0.0 for j in range(H)],
                             name="Set by the scenario", marker_color=DRIVER_COLOUR["_set"],
                             hovertemplate="%{x}: %{y:+.2f}<extra>set</extra>"))
    key = ev["driver"].where(ev["driver"] != v, "_momentum")
    order = list(_shares(e, v).index)
    for k in order:
        part = ev[key == k].groupby("year")["part"].sum()
        y = [float(part.get(j, 0.0)) for j in range(1, H + 1)]
        nm = "Own momentum" if k == "_momentum" else labels.get(k, k)
        fig.add_trace(go.Bar(x=xs, y=y, name=nm,
                             marker_color=DRIVER_COLOUR.get(k, "#6250d6"),
                             hovertemplate="%{x}: %{y:+.2f}<extra>" + esc(nm) + "</extra>"))
    fig.add_trace(go.Scatter(x=xs, y=p, mode="markers", name="Total",
                             marker=dict(size=9, color="#1f2430", symbol="diamond"),
                             hovertemplate="%{x}: %{y:+.2f}<extra>total</extra>"))
    fig.update_layout(barmode="relative", height=230, bargap=0.38,
                      margin=dict(l=6, r=6, t=6, b=6), plot_bgcolor="white",
                      paper_bgcolor="white", font=dict(size=11, color="#4a5162"),
                      legend=dict(orientation="h", y=-0.18, x=0, font=dict(size=10.5)),
                      yaxis=dict(gridcolor="#f2eff6", zerolinecolor="#cfc8da"))
    fig.update_traces(marker_line_color="white", marker_line_width=1, selector=dict(type="bar"))
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def transmission(explain: list, paths: list, links: list, about: dict) -> None:
    """How the shock travels: the graph of drivers and the variables they
    move, then each linked variable in a sentence and a chart of its parts."""
    e = pd.DataFrame(explain)
    d = moved(paths)
    if not len(d):
        st.caption("Nothing moves.")
        return
    if not len(e):
        st.caption("The scenario sets every variable it moves; nothing is passed on through "
                   "the linked effects.")
        return
    lk = pd.DataFrame(links)
    labels = dict(zip(pd.DataFrame(paths)["variable"], pd.DataFrame(paths)["label"]))
    H = int(d["year"].nunique())
    years = sorted(d["year"].unique())
    st.markdown("**How the shock travels**", help=HELP["transmission"])
    st.graphviz_chart(_graph(d, e), use_container_width=False)
    st.markdown("**Each linked variable**", help=HELP["explained"])
    def _visible(v):
        """Whether the linked effects move a variable by a visible amount:
        0.05, or for a variable the scenario also sets, 5% of its largest
        move (oil's 0.1% after a 48% fall is not worth a chart)."""
        g = d[d["variable"] == v]
        lk = g[~g["set"].astype(bool)] if "set" in g else g
        if not len(lk):
            return False
        floor = 0.05 if len(lk) == len(g) else max(0.05, 0.05 * float(g["move"].abs().max()))
        return float(lk["move"].abs().max()) >= floor
    vs = [v for v in dict.fromkeys(d["variable"]) if (e["variable"] == v).any() and _visible(v)]
    for i in range(0, len(vs), 2):
        cols = st.columns(2, gap="medium")
        for c, v in zip(cols, vs[i:i + 2]):
            g = d[d["variable"] == v].sort_values("year")
            g = g.assign(t=g["year"].map({y: j for j, y in enumerate(years)}))
            u = unit(g["unit"].iloc[0])
            with c.container(border=True):
                st.markdown(f"**{labels.get(v, v)}** ({u})", help=about.get(v) or None)
                st.markdown(f'<div class="scn-say">{esc(sentence(v, labels.get(v, v), u, g["move"].tolist(), [bool(s) for s in g["set"]] if "set" in g else [False] * H, e, lk, labels))}</div>',
                            unsafe_allow_html=True)
                _bars(v, g, e, labels, H)
