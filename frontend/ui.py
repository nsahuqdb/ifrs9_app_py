"""
Shared pieces for the Streamlit interface.

Presentation only. The frontend never imports the calculation package: every
number arrives from the backend through `api.py`, so the interface cannot
quietly compute something the API would not return.

Formatting is centralised because provisions are large numbers read by people:
grouped, never scientific, and a missing value shows as a dash rather than
"nan". So is colour: a finding is red, amber, blue, green or grey by its
severity everywhere in the app, from the same few classes.
"""
from __future__ import annotations

import html
import re
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import streamlit as st

ASSETS = Path(__file__).parent / "assets"

# QDB plum, carried over from the R app so the two look related.
PLUM = "#5b1f6e"
PLUM_LIGHT = "#8e5aa3"
TEAL = "#0d9488"
OK = "#059669"
WARN = "#d97706"
ERR = "#dc2626"
GREY = "#8a94a6"
SEQ = [PLUM, PLUM_LIGHT, TEAL, "#c9a9d8", "#7c3aed", "#5eead4", GREY, WARN]

# Severity -> tone. One mapping, used by every badge, row and tile.
_TONE = {"ERROR": "err", "FAIL": "err", "WARN": "warn", "WARNING": "warn",
         "INFO": "info", "PASS": "ok", "OK": "ok", "ACCEPTED": "muted",
         "SUPPRESSED": "muted",
         # a standing suppression's state
         "ACTIVE": "info", "EXPIRED": "muted", "REMOVED": "muted"}
_ORDER = {"err": 0, "warn": 1, "info": 2, "muted": 3, "ok": 4}

CSS = """
<style>
  :root {
    --plum:#5b1f6e; --plum-2:#7c3492; --plum-50:#faf7fc; --plum-100:#f3ecf7;
    --plum-200:#e4d6ec;
    --ink:#1f2430; --ink-2:#344054; --muted:#667085; --faint:#98a2b3;
    --line:#e7e4ed; --line-2:#f1eef5; --page:#f6f5f9;
    --err:#b42318; --err-bg:#fef3f2; --err-line:#fecdca; --err-solid:#d92d20;
    --warn:#b54708; --warn-bg:#fffaeb; --warn-line:#fedf89; --warn-solid:#f79009;
    --info:#175cd3; --info-bg:#eff8ff; --info-line:#b2ddff; --info-solid:#2e90fa;
    --ok:#067647; --ok-bg:#ecfdf3; --ok-line:#abefc6; --ok-solid:#17b26a;
    --mute:#475467; --mute-bg:#f2f4f7; --mute-line:#d0d5dd; --mute-solid:#98a2b3;
    --mono: "Source Code Pro", ui-monospace, SFMono-Regular, Menlo, monospace;
  }

  /* ---- the page: full width with gutters, a faint tint behind white cards */
  .stApp, [data-testid="stAppViewContainer"] {background: var(--page);}
  [data-testid="stMainBlockContainer"], .block-container {
      max-width: none !important;
      padding: 4.6rem 1.75rem 2.5rem 1.75rem !important;}
  @media (min-width: 2400px) {
    [data-testid="stMainBlockContainer"], .block-container {
        max-width: 2240px !important; margin: 0 auto;}}
  [data-testid="stVerticalBlock"] {gap: .75rem;}

  /* ---- header: logo and menu on one white bar */
  header[data-testid="stHeader"] {background: #fff;
      border-bottom: 1px solid var(--line);
      box-shadow: 0 1px 2px rgba(16,24,40,.04);}
  [data-testid="stAppDeployButton"] {display: none !important;}
  /* a thin moving bar under the header while the page is working -- the
     app's "busy" signal, since the toolbar's running widget is hidden */
  .stApp[data-test-script-state="running"] header[data-testid="stHeader"]::after {
      content: ""; position: absolute; left: 0; right: 0; bottom: -1px; height: 3px;
      background: linear-gradient(90deg, transparent, var(--plum), #b07cc6, transparent);
      background-size: 40% 100%; background-repeat: no-repeat; opacity: 0;
      animation: qdb-in .01s linear .3s forwards, qdb-run 1.2s linear .3s infinite;}
  @keyframes qdb-in {to {opacity: 1;}}
  @keyframes qdb-run {from {background-position: -70% 0;} to {background-position: 170% 0;}}
  [data-testid="stHeaderLogo"], img[data-testid="stLogo"] {
      height: 2.35rem !important; max-height: 2.35rem !important;
      width: auto !important; margin-right: 1.1rem;}
  [data-testid="stTopNavSection"], [data-testid="stTopNavLink"] {
      font-weight: 600; color: var(--ink-2); border-radius: 8px;}
  [data-testid="stTopNavSection"]:hover, [data-testid="stTopNavLink"]:hover {
      background: var(--plum-100); color: var(--plum);}
  [data-testid="stTopNavSection"] p, [data-testid="stTopNavLink"] p {
      font-size: .9rem !important;}

  /* ---- type */
  h1 {font-size: 1.35rem !important; font-weight: 700; letter-spacing: -0.015em;}
  h2 {font-size: 1.05rem !important; font-weight: 700; letter-spacing: -0.01em;
      margin: 1.1rem 0 .1rem !important; color: #2a2f3a;}
  h3 {font-size: .95rem !important; font-weight: 700; color: var(--ink-2);}
  h4 {font-size: .95rem !important; font-weight: 700; color: var(--ink);}
  hr {margin: .9rem 0 !important;}
  code {font-size: .82em; color: #5b1f6e; background: var(--plum-50);
        padding: 1px 5px; border-radius: 5px;}

  .pg-head {display: flex; align-items: baseline; gap: .9rem;
      flex-wrap: wrap; margin: 0 0 .15rem;}
  .pg-title {font-size: 1.4rem; font-weight: 700; color: var(--ink);
      letter-spacing: -.015em; line-height: 1.2;}
  .pg-sub {color: var(--muted); font-size: .88rem; line-height: 1.45;}

  /* ---- cards: bordered containers are white panels on the tinted page */
  [data-testid="stVerticalBlockBorderWrapper"],
  div[data-testid="stVerticalBlock"][class*="border"] {
      background: #fff; border-radius: 12px !important;
      border-color: var(--line) !important;
      box-shadow: 0 1px 2px rgba(16,24,40,.04);}
  .card-h {display: flex; align-items: center; gap: .6rem;
      margin: -.1rem 0 .35rem;}
  .card-h .num {width: 24px; height: 24px; border-radius: 50%; flex: none;
      display: grid; place-items: center; font-size: .78rem; font-weight: 700;
      background: var(--plum-100); color: var(--plum);}
  .card-h .num.done {background: var(--ok-bg); color: var(--ok);}
  .card-h .num.err {background: var(--err-bg); color: var(--err);}
  .card-h .t {font-weight: 700; font-size: 1rem; color: var(--ink);}
  .card-h .r {margin-left: auto;}

  /* ---- metrics */
  div[data-testid="stMetric"] {
      background: #fff; border: 1px solid var(--line);
      border-left: 3px solid var(--plum); border-radius: 10px;
      padding: 10px 14px 8px; box-shadow: 0 1px 2px rgba(16,24,40,.04);}
  div[data-testid="stMetricLabel"] p {
      font-size: .68rem !important; text-transform: uppercase;
      letter-spacing: .06em; color: var(--muted); font-weight: 700;}
  div[data-testid="stMetricValue"] {
      font-size: 1.38rem !important; font-weight: 700; color: var(--ink);
      font-variant-numeric: tabular-nums; letter-spacing: -0.02em;}
  div[data-testid="stMetricDelta"] {font-size: .74rem !important;}

  /* ---- tables, tabs, expanders, buttons */
  div[data-testid="stDataFrame"] {border: 1px solid var(--line);
      border-radius: 10px; overflow: hidden; background: #fff;}
  div[data-testid="stDataFrame"] * {font-variant-numeric: tabular-nums;}
  .stTabs [data-baseweb="tab-list"] {gap: 2px; border-bottom: 1px solid var(--line);}
  .stTabs [data-baseweb="tab"] {height: 36px; padding: 0 14px; font-weight: 600;
      font-size: .88rem;}
  .stTabs [aria-selected="true"] {background: var(--plum-100);
      border-radius: 8px 8px 0 0; color: var(--plum);}
  div[data-testid="stExpander"] {border: 1px solid var(--line);
      border-radius: 10px; background: #fff;}
  div[data-testid="stExpander"] summary p {font-weight: 600;}
  .stButton button, .stDownloadButton button, .stFormSubmitButton button {
      font-weight: 600; border-radius: 8px;}
  /* page links read as buttons: they are the "go there next" actions */
  [data-testid="stPageLink"] a {border: 1px solid var(--line); background: #fff;
      border-radius: 8px; padding: .3rem .85rem; justify-content: center;}
  [data-testid="stPageLink"] a:hover {border-color: var(--plum-200);
      background: var(--plum-50);}
  [data-testid="stPageLink"] a p {font-weight: 600;}
  .stButton button[kind="primary"], .stFormSubmitButton button[kind="primary"] {
      background: var(--plum); border: 0;
      box-shadow: 0 1px 3px rgba(91,31,110,.25);}
  .stButton button[kind="primary"]:hover,
  .stFormSubmitButton button[kind="primary"]:hover {background: #6d2a83;}
  /* a disabled primary button keeps its label readable */
  .stButton button[kind="primary"]:disabled {background: #e9e2ee;
      color: #6f5f78; box-shadow: none; opacity: 1; cursor: not-allowed;}

  /* ---- small text and pills */
  .caption, [data-testid="stMarkdownContainer"] p.caption {color: var(--muted);
      font-size: .82rem; margin: 0 0 .35rem; line-height: 1.5;}
  .caption code {font-size: .78rem;}
  .pill {display: inline-block; padding: 2px 10px; border-radius: 999px;
      font-size: .72rem; font-weight: 700; letter-spacing: .02em;
      border: 1px solid transparent;}
  .pill-ok {background: var(--ok-bg); color: var(--ok); border-color: var(--ok-line);}
  .pill-warn {background: var(--warn-bg); color: var(--warn); border-color: var(--warn-line);}
  .pill-err {background: var(--err-bg); color: var(--err); border-color: var(--err-line);}
  .pill-info {background: var(--info-bg); color: var(--info); border-color: var(--info-line);}
  .pill-muted {background: var(--mute-bg); color: var(--mute); border-color: var(--mute-line);}
  .pill-plum {background: var(--plum-100); color: var(--plum); border-color: var(--plum-200);}

  /* ---- chips: counts by severity */
  .chips {display: flex; flex-wrap: wrap; gap: 6px; margin: .1rem 0 .3rem;}
  .chip {display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px;
      border-radius: 999px; font-size: .78rem; font-weight: 600; border: 1px solid;
      line-height: 1.5;}
  .chip b {font-variant-numeric: tabular-nums; font-weight: 800;}
  .chip.err {background: var(--err-bg); color: var(--err); border-color: var(--err-line);}
  .chip.warn {background: var(--warn-bg); color: var(--warn); border-color: var(--warn-line);}
  .chip.info {background: var(--info-bg); color: var(--info); border-color: var(--info-line);}
  .chip.ok {background: var(--ok-bg); color: var(--ok); border-color: var(--ok-line);}
  .chip.muted {background: var(--mute-bg); color: var(--mute); border-color: var(--mute-line);}
  .chip.plum {background: var(--plum-100); color: var(--plum); border-color: var(--plum-200);}

  /* ---- callouts: a verdict in one line */
  .callout {display: flex; gap: .65rem; align-items: flex-start;
      border-radius: 10px; padding: .6rem .85rem; border: 1px solid;
      font-size: .87rem; line-height: 1.45; margin: .15rem 0 .35rem;}
  .callout .ic {font-weight: 800; flex: none; width: 1.2rem; text-align: center;}
  .callout ul {margin: .3rem 0 .35rem 1.1rem; padding: 0;}
  .callout li {margin: .1rem 0;}
  .callout.err {background: var(--err-bg); border-color: var(--err-line); color: #7a271a;}
  .callout.warn {background: var(--warn-bg); border-color: var(--warn-line); color: #7a2e0e;}
  .callout.info {background: var(--info-bg); border-color: var(--info-line); color: #194185;}
  .callout.ok {background: var(--ok-bg); border-color: var(--ok-line); color: #054f31;}
  .callout.muted {background: var(--mute-bg); border-color: var(--mute-line); color: var(--ink-2);}
  .callout.plum {background: var(--plum-50); border-color: var(--plum-200); color: var(--ink);}
  .callout .ic.err {color: var(--err-solid);} .callout .ic.warn {color: var(--warn-solid);}
  .callout .ic.info {color: var(--info-solid);} .callout .ic.ok {color: var(--ok-solid);}

  /* ---- findings: one row per check, coloured by severity */
  .fx {display: flex; flex-direction: column; gap: 6px;}
  .fx-row {display: grid; grid-template-columns: 84px 1fr; gap: 10px;
      align-items: start; padding: 8px 12px; background: #fff;
      border: 1px solid var(--line); border-left: 4px solid var(--mute-solid);
      border-radius: 10px;}
  .fx-row.err {border-left-color: var(--err-solid); background: #fffbfa;}
  .fx-row.warn {border-left-color: var(--warn-solid); background: #fffdf6;}
  .fx-row.info {border-left-color: var(--info-solid);}
  .fx-row.ok {border-left-color: var(--ok-solid);}
  .fx-row.muted {border-left-color: var(--mute-solid); background: #fbfbfc;}
  .fx-sev {margin-top: 1px; font-size: .66rem; padding: 2px 0; text-align: center;}
  .fx-title {font-weight: 600; color: var(--ink); font-size: .88rem; line-height: 1.35;}
  .fx-id {font-family: var(--mono); font-size: .7rem; color: var(--faint);
      font-weight: 500; margin-left: .4rem; white-space: nowrap;}
  .fx-msg {color: var(--ink-2); font-size: .84rem; line-height: 1.45;
      margin-top: 2px; overflow-wrap: anywhere;}
  .fx-fix {color: var(--muted); font-size: .78rem; margin-top: 3px;}
  .fx-fix b {color: var(--ink-2);}
  .fx-acc {font-size: .8rem; margin-top: 4px; padding: 3px 8px; border-radius: 6px;
      background: var(--plum-50); color: var(--plum); border: 1px solid var(--plum-200);
      display: inline-block;}
  .fx-empty {color: var(--muted); font-size: .86rem; padding: .5rem 0;}

  /* ---- KPI tiles */
  .kpis {display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 10px; margin: .1rem 0 .4rem;}
  .kpi {background: #fff; border: 1px solid var(--line); border-radius: 12px;
      padding: 9px 14px 8px; border-top: 3px solid var(--mute-line);}
  .kpi .l {font-size: .68rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: .05em; color: var(--muted);}
  .kpi .v {font-size: 1.4rem; font-weight: 750; color: var(--ink);
      font-variant-numeric: tabular-nums; letter-spacing: -.02em; line-height: 1.25;}
  .kpi .n {font-size: .74rem; color: var(--muted);}
  .kpi.err {border-top-color: var(--err-solid);} .kpi.err .v {color: var(--err);}
  .kpi.warn {border-top-color: var(--warn-solid);} .kpi.warn .v {color: var(--warn);}
  .kpi.ok {border-top-color: var(--ok-solid);} .kpi.ok .v {color: var(--ok);}
  .kpi.info {border-top-color: var(--info-solid);}
  .kpi.plum {border-top-color: var(--plum);}

  /* ---- stepper */
  .steps {display: flex; align-items: center; background: #fff;
      border: 1px solid var(--line); border-radius: 12px; padding: 9px 16px;
      margin: .25rem 0 .1rem; box-shadow: 0 1px 2px rgba(16,24,40,.04);}
  .step {display: flex; align-items: center; gap: 8px; flex: 1; min-width: 0;
      color: var(--faint); font-size: .86rem; font-weight: 600; white-space: nowrap;}
  .step:last-child {flex: 0 0 auto;}
  .step .dot {width: 24px; height: 24px; border-radius: 50%; flex: none;
      display: grid; place-items: center; font-size: .74rem; font-weight: 700;
      background: var(--mute-bg); color: var(--mute); border: 1px solid var(--mute-line);}
  .step .sub {font-weight: 500; color: var(--faint); font-size: .76rem;}
  .step .bar {flex: 1; height: 2px; background: var(--line); margin: 0 12px;
      border-radius: 2px; min-width: 16px;}
  .step.done {color: var(--ink-2);}
  .step.done .dot {background: var(--ok-bg); color: var(--ok); border-color: var(--ok-line);}
  .step.done .bar {background: var(--ok-line);}
  .step.now {color: var(--ink);}
  .step.now .dot {background: var(--plum); color: #fff; border-color: var(--plum);
      box-shadow: 0 0 0 4px var(--plum-100);}
  .step.err {color: var(--err);}
  .step.err .dot {background: var(--err-bg); color: var(--err); border-color: var(--err-line);}

  /* ---- empty state */
  .empty {text-align: center; padding: 2.2rem 1rem 1.6rem; color: var(--muted);}
  .empty .t {font-size: 1.05rem; font-weight: 700; color: var(--ink); margin-bottom: .3rem;}
  .empty .s {font-size: .88rem; max-width: 560px; margin: 0 auto; line-height: 1.5;}

  /* ---- who is signed in, at the right of the header bar. Its element
     container is taken out of the page flow so it adds no gap. */
  [data-testid="stElementContainer"]:has(.hdr-user) {position: absolute !important;
      width: 0 !important; height: 0 !important; margin: 0 !important;}
  .hdr-user {position: fixed; top: 0; right: 1.1rem; height: 56px; z-index: 1000001;
      display: flex; align-items: center; gap: .55rem;}
  .hdr-user .av {width: 30px; height: 30px; border-radius: 50%; display: grid;
      place-items: center; background: var(--plum-100); color: var(--plum);
      border: 1px solid var(--plum-200); font-weight: 700; font-size: .78rem;}
  .hdr-user b {display: block; font-size: .8rem; color: var(--ink-2);
      line-height: 1.15; font-weight: 600;}
  .hdr-user small {display: block; font-size: .68rem; color: var(--faint);
      line-height: 1.15;}

  /* ---- what gets checked, before anything has been */
  .howto {display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 10px; margin: 0 .5rem 1rem;}
  .howto > div {background: var(--plum-50); border: 1px solid var(--plum-200);
      border-radius: 10px; padding: 10px 14px; font-size: .84rem;
      color: var(--ink-2); line-height: 1.45;}
  .howto b {display: block; color: var(--plum); margin-bottom: 3px;}

  /* ---- the run bar on analysis pages */
  .runbar-label {font-size: .7rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: .06em; color: var(--muted); padding-top: .55rem;}
</style>
"""


# ------------------------------------------------------------- markdown --
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`([^`]+)`")
_ITAL = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])")


def md(text) -> str:
    """The little markdown the app's own sentences use -- **bold**, `code`,
    *italic* -- as safe HTML. Text inside an HTML block is not run through
    markdown by Streamlit, which is how "**that folder does not exist**" came
    to be shown with its asterisks; and a Windows path's backslashes must
    arrive untouched, so everything is escaped first."""
    s = html.escape(str(text if text is not None else ""), quote=False)
    s = _CODE.sub(lambda m: f"<code>{m.group(1)}</code>", s)
    s = _BOLD.sub(r"<b>\1</b>", s)
    s = _ITAL.sub(r"<i>\1</i>", s)
    return s


def esc(text) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


# ---------------------------------------------------------------- page --
def flash(message: str) -> None:
    """Keep a confirmation for the next run of the page.

    An action that ends in st.rerun() -- approve, create, promote -- would
    otherwise show its success message for a frame and lose it; the R app
    shows a notification that stays. page_setup() shows it once, at the top.
    """
    st.session_state["_flash"] = message


def inject_css() -> None:
    """The stylesheet, once per run. Sent with st.html so it takes no space:
    style-only HTML goes to Streamlit's event container, not the page."""
    st.html(CSS)


def _nice_date(v) -> str:
    """"2026-06-30" or R's "6/30/2026" as "30 Jun 2026"; "" when unknown."""
    from datetime import date, datetime
    t = str(v or "").strip()
    if t.upper() in ("", "NA", "NAN", "NONE", "NAT"):
        return ""
    try:
        return date.fromisoformat(t[:10]).strftime("%d %b %Y")
    except ValueError:
        pass
    try:
        return datetime.strptime(t, "%m/%d/%Y").strftime("%d %b %Y")
    except ValueError:
        return t


def run_label(r: dict) -> str:
    """How a run reads in a picker: id, portfolio date, run type and, for an
    official run, where it is in approval."""
    bits = [str(r["run_id"])]
    d = _nice_date(r.get("portfolio_date"))
    if d:
        bits.append(d)
    rt = str(r.get("run_type") or "").strip().lower()
    status = str(r.get("status") or "").strip().lower().replace("_", " ")
    if rt:
        bits.append(rt.capitalize())
    if status and status != rt:
        bits.append(status)
    return " · ".join(bits)


def _set_run():
    st.session_state["run_id"] = st.session_state["_pick_run"]


def _set_cmp():
    st.session_state["compare_id"] = st.session_state["_pick_cmp"]


def _reload():
    import api
    api.clear()


def page_setup(title: str, subtitle: str | None = None) -> None:
    """The page's title row. On a page that reads a run, the run picker sits
    at its right (and the comparison run beside it where the page compares
    two), so which run is on screen is never out of sight."""
    S = st.session_state
    sub = f'<div class="pg-sub">{md(subtitle)}</div>' if subtitle else ""
    head = (f'<div class="pg-head"><div class="pg-title">{esc(title)}</div>'
            f'{sub}</div>')
    rb = S.get("_runbar")
    if not rb or not rb.get("runs"):
        st.markdown(head, unsafe_allow_html=True)
    else:
        runs = rb["runs"]
        ids = [r["run_id"] for r in runs]
        labels = {r["run_id"]: run_label(r) for r in runs}
        cmp = rb["mode"] == "compare" and len(ids) > 1
        cols = st.columns([6, 4, 4, 0.55] if cmp else [10, 4, 0.55],
                          vertical_alignment="center", gap="small")
        cols[0].markdown(head, unsafe_allow_html=True)
        # The picker's own key is re-seeded from run_id on every page: a
        # widget's state is dropped on pages that do not draw it. The labels
        # sit inside the options, so the title row stays one line high.
        S["_pick_run"] = S.get("run_id") if S.get("run_id") in ids else ids[0]
        cols[1].selectbox("Run", ids, format_func=lambda i: f"Run: {labels[i]}",
                          key="_pick_run", on_change=_set_run,
                          label_visibility="collapsed")
        if cmp:
            others = [i for i in ids if i != S["_pick_run"]]
            S["_pick_cmp"] = (S.get("compare_id") if S.get("compare_id") in others
                              else others[0])
            cols[2].selectbox("Compared with", others,
                              format_func=lambda i: f"Against: {labels[i]}",
                              key="_pick_cmp", on_change=_set_cmp,
                              label_visibility="collapsed")
        cols[-1].button("", icon=":material/refresh:", key="_reload",
                        help="Reload the runs from disk", on_click=_reload)
    # The slot exists on every run, message or not: an element that comes and
    # goes above the page's tabs would shift them and reset the open tab.
    slot = st.empty()
    msg = S.pop("_flash", None)
    if msg:
        slot.success(msg, icon="✅")


def header_badge(user: str, engine: str, backend: str) -> None:
    """The acting user (IFRS9_USER, else the OS user) and the engine version,
    at the right of the header -- the name every form records."""
    ini = (str(user or "?").strip()[:1] or "?").upper()
    st.markdown(f'<div class="hdr-user" title="{esc(backend)}"><span class="av">'
                f'{esc(ini)}</span><span><b>{esc(user or "unknown user")}</b>'
                f'<small>engine {esc(engine)}</small></span></div>',
                unsafe_allow_html=True)


def backend_down(error: str, backend: str) -> None:
    """The whole app depends on the backend; say so once, plainly, with the
    command that starts it."""
    st.markdown(
        '<div class="empty" style="padding-top:3.2rem">'
        '<div class="t">The calculation service is not reachable</div>'
        '<div class="s">This window draws the pages; the backend does the '
        'calculating. Start it in a second terminal, from the app folder, then '
        'press <b>Try again</b>.</div></div>', unsafe_allow_html=True)
    from urllib.parse import urlparse
    port = urlparse(backend).port or 8000
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        st.code(f"uvicorn backend.main:app --port {port}", language="bash")
        caption(f"The app is looking for it at `{backend}` (set `IFRS9_BACKEND` "
                "to change that).")
        if st.button("Try again", type="primary", icon=":material/refresh:"):
            import api
            api.clear()
            st.rerun()
        with st.expander("Technical detail"):
            st.code(error, language=None)


def no_runs(title: str, runs: list, pipeline_page) -> None:
    """A page that reads a run, opened before there is one."""
    st.session_state["_runbar"] = None
    page_setup(title)
    with st.container(border=True):
        if runs:
            empty_state("No run has an ECL report yet",
                        f"{len(runs)} run folder(s) were found, but none has been "
                        "priced to the end. Finish a run on **Run the pipeline** "
                        "and it appears here.")
        else:
            empty_state("No ECL run to show yet",
                        "This page reads a finished run. Build one on **Run the "
                        "pipeline**: validate the input extracts, check they can "
                        "be priced, then start the run.")
        _, mid, _ = st.columns([2, 1, 2])
        mid.page_link(pipeline_page, label="Go to Run the pipeline",
                      icon=":material/play_circle:", width="stretch")
    import api
    try:
        d = api.diagnose()
    except api.BackendError:
        d = None
    if d:
        with st.expander("Where the app looks for runs"):
            caption(f"Runs folder: `{d['resolved_to']}` · exists: **{d['exists']}**"
                    f" · backend working directory: `{d['working_directory']}`")
            if d.get("hint"):
                callout("info", d["hint"])
            for e in (d.get("entries") or [])[:12]:
                why = "" if e["accepted"] else f" — {e.get('reason', '')}"
                caption(("✓ " if e["accepted"] else "✗ ") + f"`{e['name']}`{why}")


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
    st.markdown(f'<p class="caption">{md(text)}</p>', unsafe_allow_html=True)


def pill(text: str, tone: str = "info") -> str:
    return f'<span class="pill pill-{tone}">{esc(text)}</span>'


def tone_of(severity) -> str:
    return _TONE.get(str(severity or "").strip().upper(), "muted")


def card_header(title: str, num=None, state: str = "", right: str = "") -> None:
    """A card's title row: a numbered dot (plum, green when done, red when
    blocked), the title, and an optional right-aligned pill."""
    n = (f'<span class="num {esc(state)}">{"✓" if state == "done" else esc(num)}</span>'
         if num is not None else "")
    r = f'<span class="r">{right}</span>' if right else ""
    st.markdown(f'<div class="card-h">{n}<span class="t">{esc(title)}</span>{r}</div>',
                unsafe_allow_html=True)


def callout(tone: str, text: str, title: str | None = None,
            items: list[str] | None = None, after: str | None = None) -> None:
    """A one-line verdict, coloured by tone: err, warn, info, ok, muted, plum.
    ``items`` are listed under the text, one per line, and ``after`` closes
    it."""
    icon = {"err": "!", "warn": "!", "info": "i", "ok": "✓", "muted": "•",
            "plum": "›"}.get(tone, "•")
    head = f"<b>{esc(title)}</b> " if title else ""
    lis = ("<ul>" + "".join(f"<li>{md(i)}</li>" for i in items) + "</ul>"
           if items else "")
    tail = md(after) if after else ""
    st.markdown(f'<div class="callout {tone}"><span class="ic {tone}">{icon}</span>'
                f'<div>{head}{md(text)}{lis}{tail}</div></div>', unsafe_allow_html=True)


def chips(items) -> None:
    """Counts as coloured chips: [(tone, count, label), ...]; zero counts are
    left out unless every count is zero."""
    items = [i for i in items if i[1]] or items[:0]
    if not items:
        return
    st.markdown('<div class="chips">' + "".join(
        f'<span class="chip {t}"><b>{esc(n)}</b> {esc(lab)}</span>'
        for t, n, lab in items) + "</div>", unsafe_allow_html=True)


def kpis(items) -> None:
    """KPI tiles: [(label, value, tone, note), ...]; the tone colours the
    tile's top rule and, for err/warn/ok, the figure."""
    cells = []
    for it in items:
        label, value = it[0], it[1]
        tone = it[2] if len(it) > 2 and it[2] else ""
        note = it[3] if len(it) > 3 and it[3] else ""
        cells.append(f'<div class="kpi {tone}"><div class="l">{esc(label)}</div>'
                     f'<div class="v">{esc(value)}</div>'
                     + (f'<div class="n">{md(note)}</div>' if note else "") + "</div>")
    st.markdown('<div class="kpis">' + "".join(cells) + "</div>", unsafe_allow_html=True)


def stepper(steps) -> None:
    """Where the user is in a flow: [(label, state, sub), ...] with state
    done | now | err | "" (to come)."""
    out = []
    for i, (label, state, sub) in enumerate(steps, start=1):
        dot = "✓" if state == "done" else ("!" if state == "err" else str(i))
        bar = '<span class="bar"></span>' if i < len(steps) else ""
        s = f'<span class="sub">{esc(sub)}</span>' if sub else ""
        out.append(f'<div class="step {state}"><span class="dot">{dot}</span>'
                   f'<span>{esc(label)}<br>{s}</span>{bar}</div>')
    st.markdown('<div class="steps">' + "".join(out) + "</div>", unsafe_allow_html=True)


def empty_state(title: str, text: str) -> None:
    st.markdown(f'<div class="empty"><div class="t">{esc(title)}</div>'
                f'<div class="s">{md(text)}</div></div>', unsafe_allow_html=True)


def findings(rows, empty: str = "Nothing to report.", why: bool = False) -> None:
    """Validation findings as readable rows, worst first.

    Each row is a dict with any of: severity (or effective_severity), id,
    context, title (or description), message, where, remediation, rationale,
    suppressed, accepted_note. A suppressed finding shows as ACCEPTED in grey:
    it stays on the record but no longer blocks; ``accepted_note`` says who
    accepted it, how and why. ``why`` adds the rationale -- why the
    check matters -- for pages where findings are reviewed rather than
    triaged.
    """
    rows = list(rows or [])
    if not rows:
        st.markdown(f'<div class="fx-empty">{md(empty)}</div>', unsafe_allow_html=True)
        return

    def sev(r):
        if r.get("suppressed") in (True, "True", "TRUE", "true", 1):
            return "ACCEPTED"
        return str(r.get("effective_severity") or r.get("severity") or "INFO").upper()

    rows = sorted(rows, key=lambda r: (_ORDER.get(tone_of(sev(r)), 5),
                                       str(r.get("id", ""))))
    out = []
    for r in rows:
        s = sev(r)
        t = tone_of(s)
        title = r.get("title") or r.get("description") or r.get("id") or ""
        msg = str(r.get("message") or "")
        if msg.strip() == str(title).strip():
            msg = ""
        ident = " · ".join(x for x in (str(r.get("id") or ""),
                                       str(r.get("context") or "")) if x and x != "nan")
        where = str(r.get("where") or "")
        fix = str(r.get("remediation") or "")
        rat = str(r.get("rationale") or "") if why else ""
        hint = " · ".join(
            x for x in (md(where) if where and where != "nan" else "",
                        f"<b>Fix:</b> {md(fix)}" if fix and fix != "nan" else "")
            if x)
        out.append(
            f'<div class="fx-row {t}"><span class="pill pill-{t} fx-sev">{esc(s)}</span>'
            f'<div><div class="fx-title">{md(title)}'
            + (f'<span class="fx-id">{esc(ident)}</span>' if ident else "")
            + "</div>"
            + (f'<div class="fx-msg">{md(msg)}</div>' if msg else "")
            + (f'<div class="fx-fix"><b>Why it matters:</b> {md(rat)}</div>'
               if rat and rat != "nan" else "")
            + (f'<div class="fx-fix">↳ {hint}</div>' if hint else "")
            + (f'<div class="fx-acc">✓ {md(r["accepted_note"])}</div>'
               if r.get("accepted_note") else "")
            + "</div></div>")
    st.markdown('<div class="fx">' + "".join(out) + "</div>", unsafe_allow_html=True)


def accepted_note(r: dict) -> str:
    """What accepted a suppressed finding, in one line: an acceptance for
    this run or a standing suppression, who, and why."""
    src = r.get("accepted_source") or r.get("source")
    reason = r.get("accepted_reason") or r.get("reason") or ""
    who = r.get("accepted_by") or "?"
    if src == "run":
        return f"Accepted for this run by **{who}** — {reason}"
    if src == "standing":
        until = r.get("valid_until") or ""
        return (f"Standing suppression approved by **{who}**"
                + (f", valid until {until}" if until else "") + f" — {reason}")
    return ""


def accepted_findings_table(rows, empty: str | None = None) -> None:
    """The findings accepted in a run, and why: each check, its severity,
    whether it was accepted for the run or by a standing suppression, the
    reason, who, when, until when, and whether it took effect."""
    rows = list(rows or [])
    if not rows:
        if empty:
            caption(empty)
        return
    df = pd.DataFrame(rows)

    def col(c):
        return df[c] if c in df.columns else pd.Series([""] * len(df))
    show = pd.DataFrame({
        "Check": col("validator_id"),
        "Severity": col("severity"),
        "Accepted": col("source").map({"run": "for this run",
                                       "standing": "standing suppression"})
        .fillna("—"),
        "Reason": col("reason"),
        "By": col("accepted_by"),
        "When": col("accepted_at").astype(str).str[:16].str.replace("T", " "),
        "Until": col("valid_until"),
        "In effect": col("in_effect").map(
            lambda v: "yes" if str(v).upper() == "TRUE" else "no"),
    })
    st.dataframe(style_severity(show, cols=("Severity",)), hide_index=True,
                 width="stretch",
                 column_config={"Reason": st.column_config.TextColumn(width="large"),
                                "Check": st.column_config.TextColumn(width="medium")})


def severity_counts(rows) -> dict:
    """{'err': n, 'warn': n, 'info': n, 'muted': n} for a list of findings."""
    out = {"err": 0, "warn": 0, "info": 0, "muted": 0, "ok": 0}
    for r in rows or []:
        if r.get("suppressed") in (True, "True", "TRUE", "true", 1):
            out["muted"] += 1
        else:
            out[tone_of(r.get("effective_severity") or r.get("severity"))] += 1
    return out


def style_severity(df: pd.DataFrame, cols=("severity", "effective_severity",
                                          "status", "Severity", "Status")):
    """A Styler colouring the severity columns of a table shown with
    st.dataframe, so a long table reads the way the findings rows do."""
    colours = {"err": ("#fef3f2", "#b42318"), "warn": ("#fffaeb", "#b54708"),
               "info": ("#eff8ff", "#175cd3"), "ok": ("#ecfdf3", "#067647"),
               "muted": ("#f2f4f7", "#475467")}

    def cell(v):
        t = tone_of(v)
        if t not in colours or not str(v or "").strip():
            return ""
        bg, fg = colours[t]
        return f"background-color: {bg}; color: {fg}; font-weight: 600"

    present = [c for c in cols if c in df.columns]
    sty = df.style
    if present:
        sty = sty.map(cell, subset=present)
    return sty


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
        title=None, height=None, fmt="%{x:,.0f}", dp: int = 0):
    """A bar chart with the app's palette.

    Diverging colours increases red and decreases green, which is the reading
    people expect for a provision.

    ``dp`` is the precision of the value label on each bar. It defaults to 0
    because most of these are currency, but a PD of 0.065 labelled "0" is
    worse than no label at all.
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
        text=[f"{v:,.{dp}f}" for v in d[y]], textposition="outside",
        textfont=dict(size=11, color="#4a5162"), cliponaxis=False,
        hovertemplate=f"%{{y}}<br>{fmt}<extra></extra>")
    fig.update_layout(
        height=height or max(230, 32 * len(d) + 80),
        margin=dict(l=8, r=64, t=42 if title else 6, b=6),
        plot_bgcolor="white", paper_bgcolor="white",
        title=dict(font=dict(size=13, color="#2a2f3a")),
        xaxis=dict(showgrid=True, gridcolor="#f4f2f7", zerolinecolor="#ded9e6",
                   tickformat=f",.{dp}f" if dp else ",", showline=False),
        yaxis=dict(showgrid=False, tickfont=dict(size=11.5)),
        showlegend=False, font=dict(size=12, color="#4a5162"), bargap=0.28,
    )
    st.plotly_chart(fig, use_container_width=True)


def waterfall(steps: pd.DataFrame, title: str | None = None, zoom: bool = False):
    """The ECL walk. Totals are absolute, the rest relative, so the bars connect.

    ``zoom`` starts the axis near the lowest point the bars reach rather than
    at zero: beside a provision in the billions the causes are otherwise too
    small to see. The totals are labelled with their full figure either way.
    """
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
    if zoom:
        level, points = 0.0, []
        for k, v in zip(steps["kind"], steps["amount"]):
            level = float(v) if k == "total" else level + float(v)
            points.append(level)
        lo, hi = min(points), max(points)
        pad = max((hi - lo) * 0.18, abs(hi) * 0.002, 1.0)
        if lo - pad > 0:
            fig.update_yaxes(range=[lo - pad, hi + pad])
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
