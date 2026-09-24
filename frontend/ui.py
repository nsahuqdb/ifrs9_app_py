"""
Shared pieces for the Streamlit interface.

Presentation only. The frontend never imports the calculation package: every
number arrives from the backend through `api.py`, so the interface cannot
quietly compute something the API would not return.

Formatting is centralised because provisions are large numbers read by people:
grouped, never scientific, and a missing value shows as a dash rather than
"nan".
"""
from __future__ import annotations

from contextlib import contextmanager

import pandas as pd
import streamlit as st

# QDB plum, carried over from the R app so the two look related.
PLUM = "#5b1f6e"
PLUM_LIGHT = "#8e5aa3"
TEAL = "#0d9488"
OK = "#059669"
WARN = "#d97706"
ERR = "#dc2626"
GREY = "#8a94a6"
SEQ = [PLUM, PLUM_LIGHT, TEAL, "#c9a9d8", "#7c3aed", "#5eead4", GREY, WARN]

CSS = """
<style>
  /* Tighter than Streamlit's defaults. The R page fitted a headline row, a
     table and a chart above the fold; the stock spacing pushes the chart off
     screen, which is what makes it feel emptier rather than any lack of
     content. */
  .block-container {padding-top: 3.2rem; padding-bottom: 3rem; max-width: 1560px;}
  h1 {font-size: 1.5rem !important; font-weight: 700; letter-spacing: -0.02em;
      margin-bottom: .15rem !important;}
  h2 {font-size: 1.02rem !important; font-weight: 700; letter-spacing: -0.01em;
      margin: 1.5rem 0 .1rem !important; color: #2a2f3a;}
  h3 {font-size: .88rem !important; font-weight: 700; color: #4a5162;}
  hr {margin: 1.1rem 0 !important;}

  /* Metric cards: a coloured rail, tabular figures, and enough contrast that a
     row of them reads as a headline strip rather than as body text. */
  div[data-testid="stMetric"] {
      background: linear-gradient(180deg,#fff 0%,#fdfcfe 100%);
      border: 1px solid #e6e3ec; border-left: 3px solid #5b1f6e;
      border-radius: 10px; padding: 11px 15px 9px;
      box-shadow: 0 1px 2px rgba(31,36,48,.05), 0 4px 14px rgba(91,31,110,.04);
      transition: box-shadow .15s ease;
  }
  div[data-testid="stMetric"]:hover {box-shadow: 0 2px 6px rgba(31,36,48,.09);}
  div[data-testid="stMetricLabel"] p {
      font-size: .68rem !important; text-transform: uppercase;
      letter-spacing: .06em; color: #8a94a6; font-weight: 700;
  }
  div[data-testid="stMetricValue"] {
      font-size: 1.42rem !important; font-weight: 700; color: #1f2430;
      font-variant-numeric: tabular-nums; letter-spacing: -0.02em;
  }
  div[data-testid="stMetricDelta"] {font-size: .74rem !important;}

  /* Brand bar, sitting above the top navigation. */
  /* The top navigation is fixed, so the banner has to sit BELOW it rather
     than at a negative offset -- otherwise it slides under the nav and the
     first line is clipped. */
  .qdb-brand {
      background: linear-gradient(100deg,#5b1f6e 0%,#7c3492 55%,#8e5aa3 100%);
      margin: 0 0 1rem; padding: 16px 24px 17px;
      border-radius: 12px;
      box-shadow: 0 2px 14px rgba(91,31,110,.18);
  }
  .qdb-brand-name {color:#fff; font-size:1.12rem; font-weight:700;
      letter-spacing:-0.01em; line-height:1.15;}
  .qdb-brand-name span {opacity:.72; font-weight:500;}
  .qdb-brand-sub {color:rgba(255,255,255,.7); font-size:.74rem;
      letter-spacing:.02em; margin-top:1px;}

  /* Top navigation: pill tabs rather than Streamlit's underline. */
  div[data-testid="stNavigationMenu"] {
      border-bottom: 1px solid #e6e3ec; padding: .35rem 0 .1rem; margin-bottom:.9rem;
  }
  div[data-testid="stNavigationMenu"] a {
      font-weight: 600 !important; font-size: .84rem !important;
      border-radius: 8px; padding: 5px 13px !important; color:#4a5162 !important;
  }
  div[data-testid="stNavigationMenu"] a:hover {background:#f7f2fa;}
  div[data-testid="stNavigationMenu"] a[aria-current="page"] {
      background:#5b1f6e !important; color:#fff !important;
  }

  section[data-testid="stSidebar"] {background: #faf9fb;
      border-right: 1px solid #e6e3ec;}
  section[data-testid="stSidebar"] h1 {font-size: 1rem !important;
      color: #5b1f6e; letter-spacing: -0.01em;}

  /* Tables: figures right-aligned and tabular, header quieter than the data. */
  div[data-testid="stDataFrame"] {border: 1px solid #e6e3ec; border-radius: 10px;
      overflow: hidden;}
  div[data-testid="stDataFrame"] * {font-variant-numeric: tabular-nums;}

  .stTabs [data-baseweb="tab-list"] {gap: 2px; border-bottom: 1px solid #e6e3ec;}
  .stTabs [data-baseweb="tab"] {height: 36px; padding: 0 15px; font-weight: 600;
      font-size: .86rem;}
  .stTabs [aria-selected="true"] {background: #f7f2fa;
      border-radius: 8px 8px 0 0; color: #5b1f6e;}

  .stButton button[kind="primary"] {background: #5b1f6e; border: 0;
      font-weight: 600; box-shadow: 0 1px 3px rgba(91,31,110,.25);}
  .stButton button[kind="primary"]:hover {background: #6d2a83;}

  div[data-testid="stExpander"] {border: 1px solid #e6e3ec; border-radius: 10px;}

  .caption {color: #8a94a6; font-size: .8rem; margin: -.3rem 0 .5rem;
      line-height: 1.45;}
  .pill {display:inline-block; padding:2px 10px; border-radius:999px;
         font-size:.7rem; font-weight:700; letter-spacing:.02em;}
  .pill-ok{background:#e7f6f0;color:#059669} .pill-warn{background:#fdf3e3;color:#d97706}
  .pill-err{background:#fce9e9;color:#dc2626} .pill-info{background:#f7f2fa;color:#5b1f6e}
</style>
"""


def page_setup(title: str, subtitle: str | None = None) -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.title(title)
    if subtitle:
        caption(subtitle)


@contextmanager
def guard():
    """Turn a backend failure into a readable message instead of a traceback.

    Every page calls the API, and the two common failures - the backend not
    running, and a run without the inputs a page needs - are the user's to fix,
    not bugs. A stack trace helps with neither.
    """
    import api
    try:
        yield
    except api.BackendError as e:
        st.error(str(e))
        st.stop()


def caption(text: str) -> None:
    st.markdown(f'<p class="caption">{text}</p>', unsafe_allow_html=True)


def pill(text: str, tone: str = "info") -> str:
    return f'<span class="pill pill-{tone}">{text}</span>'


# ------------------------------------------------------------- formatting --
def money(v, dp: int = 0) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{v:,.{dp}f}"


def pct(v, dp: int = 2) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{v:,.{dp}f}%"


def signed(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{v:+,.0f}"


def fmt_table(df: pd.DataFrame, money_cols=(), pct_cols=(), dp: int = 0) -> pd.DataFrame:
    """Format for display only. Never mutate the frame a calculation uses."""
    if df is None or len(df) == 0:
        return pd.DataFrame()
    out = df.copy()
    for c in money_cols:
        if c in out.columns:
            out[c] = out[c].map(lambda v: money(v, dp))
    for c in pct_cols:
        if c in out.columns:
            out[c] = out[c].map(lambda v: pct(v))
    return out


# ------------------------------------------------------------------ charts --
def bar(df: pd.DataFrame, x: str, y: str, *, horizontal=True, diverging=False,
        title=None, height=None, fmt="%{x:,.0f}"):
    """A bar chart with the app's palette.

    Diverging colours increases red and decreases green, which is the reading
    people expect for a provision.
    """
    import plotly.express as px

    if df is None or len(df) == 0:
        st.info("Nothing to plot.")
        return
    d = df.copy()
    if horizontal:
        d = d.iloc[::-1]
    colours = ([ERR if v >= 0 else OK for v in d[y]] if diverging
               else [PLUM] * len(d))
    fig = px.bar(d, x=y if horizontal else x, y=x if horizontal else y,
                 orientation="h" if horizontal else "v", title=title)
    # Value labels on the bars: reading a figure off an axis is slower than
    # reading it off the bar, and these are numbers people quote.
    fig.update_traces(
        marker_color=colours, marker_line_width=0,
        text=[f"{v:,.0f}" for v in d[y]], textposition="outside",
        textfont=dict(size=11, color="#4a5162"), cliponaxis=False,
        hovertemplate=f"%{{y}}<br>{fmt}<extra></extra>")
    fig.update_layout(
        height=height or max(230, 32 * len(d) + 80),
        margin=dict(l=8, r=64, t=42 if title else 6, b=6),
        plot_bgcolor="white", paper_bgcolor="white",
        title=dict(font=dict(size=13, color="#2a2f3a")),
        xaxis=dict(showgrid=True, gridcolor="#f4f2f7", zerolinecolor="#ded9e6",
                   tickformat=",", showline=False),
        yaxis=dict(showgrid=False, tickfont=dict(size=11.5)),
        showlegend=False, font=dict(size=12, color="#4a5162"), bargap=0.28,
    )
    st.plotly_chart(fig, use_container_width=True)


def waterfall(steps: pd.DataFrame, title: str | None = None):
    """The ECL walk. Totals are absolute, the rest relative, so the bars connect."""
    import plotly.graph_objects as go

    measure = ["absolute" if k == "total" else "relative" for k in steps["kind"]]
    fig = go.Figure(go.Waterfall(
        orientation="v", measure=measure,
        x=steps["label"], y=steps["amount"],
        text=[f"{v:,.0f}" for v in steps["amount"]], textposition="outside",
        connector=dict(line=dict(color="#d9d4e0")),
        increasing=dict(marker=dict(color=ERR)),
        decreasing=dict(marker=dict(color=OK)),
        totals=dict(marker=dict(color=PLUM)),
    ))
    fig.update_layout(
        title=title, height=440,
        margin=dict(l=8, r=8, t=50 if title else 18, b=8),
        plot_bgcolor="white", paper_bgcolor="white", showlegend=False,
        yaxis=dict(gridcolor="#f4f2f7", tickformat=",", zerolinecolor="#ded9e6"),
        xaxis=dict(tickfont=dict(size=11.5)),
        font=dict(size=12, color="#4a5162"),
    )
    fig.update_traces(textfont=dict(size=11), width=0.62)
    st.plotly_chart(fig, use_container_width=True)


def donut(labels, values, title=None, height=320):
    import plotly.graph_objects as go

    fig = go.Figure(go.Pie(labels=list(labels), values=list(values), hole=0.55,
                           marker=dict(colors=SEQ),
                           textinfo="label+percent", textfont=dict(size=11)))
    fig.update_traces(marker=dict(colors=SEQ, line=dict(color="white", width=2)))
    fig.update_layout(title=title, height=height, showlegend=False,
                      margin=dict(l=8, r=8, t=40 if title else 8, b=8),
                      paper_bgcolor="white",
                      font=dict(size=12, color="#4a5162"))
    st.plotly_chart(fig, use_container_width=True)


def line(df, x, y, title=None, height=320, yfmt=","):
    import plotly.express as px

    fig = px.line(df, x=x, y=y, markers=True, title=title)
    fig.update_traces(line=dict(color=PLUM, width=3), marker=dict(size=7))
    fig.update_layout(height=height, margin=dict(l=8, r=8, t=40 if title else 8, b=8),
                      plot_bgcolor="white", paper_bgcolor="white",
                      xaxis=dict(showgrid=False),
                      yaxis=dict(gridcolor="#f0eef4", tickformat=yfmt),
                      showlegend=False, font=dict(size=12))
    st.plotly_chart(fig, use_container_width=True)


def metric_row(items: list[tuple]) -> None:
    """A row of metrics. Each item is (label, value) or (label, value, delta)."""
    cols = st.columns(len(items))
    for col, item in zip(cols, items):
        label, value = item[0], item[1]
        delta = item[2] if len(item) > 2 else None
        col.metric(label, value, delta)
