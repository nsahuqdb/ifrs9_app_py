"""Ask questions about the runs, the model and the tool in plain language.

Answers come from the same analytics the pages use, the documents under Help
and the engine's code. Tables and charts are drawn from the lookups' own rows
(never retyped by the model) and every table downloads to Excel; passages the
answer relies on are listed as sources.
"""
from __future__ import annotations

import io
import re

import pandas as pd
import streamlit as st

import api
from ui import ERR, OK, PLUM, SEQ, caption, guard, page_setup

S = st.session_state
run_id = S.get("run_id")
page_setup("Assistant", "Questions about the runs, the model and the tool")

with guard():
    status = api.assistant_status()

MODELS = status.get("models") or []
usable = [m for m in MODELS if m.get("available")]
if not status.get("available") and not usable:
    st.info(status.get("reason", "The assistant is not configured."), icon="🔌")
    st.markdown(f"""
It needs an OpenAI-compatible chat endpoint, listed in the app's `config.yml`
under `assistant: models:`. A key goes in the `.env` file of the app folder,
one line per key, for example:

```
{status.get('api_key_env', 'QDB_GEMMA4_API_KEY')}=sk-...
```

The key is read on every question, so no restart is needed.
""")
    st.stop()

EXAMPLES = [
    "Show the stage split by portfolio",
    "Which portfolio moved most between the two runs?",
    "Why did the ECL change since the previous run?",
    "What are the MEV coefficients?",
    "Which validation checks failed?",
    "Top 10 customers by ECL",
    "Plot the PD curves for QDB 3, QDB 5 and QDB 7",
    "How is LGD calculated?",
    "How do I approve an overlay?",
    "Compare our collateral haircuts with Basel and QCB",
]

if "assistant_history" not in S:
    S["assistant_history"] = []
history = S["assistant_history"]


# ---------------------------------------------------------------- helpers --
def _frame(t: dict) -> pd.DataFrame:
    return pd.DataFrame(t.get("rows") or [], columns=t.get("columns") or None)


_PCT = re.compile(r"(%|coverage)", re.I)


def _column_config(df: pd.DataFrame) -> dict:
    cfg = {}
    for c in df.columns:
        vals = df[c].dropna().astype(str)
        if len(vals) and vals.str.match(r"^(https?://|regfile://)").all():
            df[c] = df[c].map(lambda v: _urls(v) if isinstance(v, str) else v)
            cfg[c] = st.column_config.LinkColumn(c, display_text="Open ↗")
            continue
        if pd.api.types.is_numeric_dtype(df[c]):
            if _PCT.search(str(c)):
                cfg[c] = st.column_config.NumberColumn(format="%.2f%%")
            elif df[c].abs().max() >= 100 if len(df) else False:
                cfg[c] = st.column_config.NumberColumn(format="localized")
    return cfg


def _sheet(name: str, used: set) -> str:
    s = re.sub(r"[\[\]:*?/\\]", " ", name)[:28].strip() or "Table"
    base, i = s, 2
    while s in used:
        s, i = f"{base[:25]} {i}", i + 1
    used.add(s)
    return s


def to_excel(tables: list[dict], question: str = "") -> bytes:
    """The tables of an answer as one workbook, a sheet each, numbers as
    numbers (not text), header bold, columns sized to fit."""
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    buf = io.BytesIO()
    used: set = set()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for t in tables:
            df = _frame(t)
            name = _sheet(t.get("title") or "Table", used)
            df.to_excel(xw, sheet_name=name, index=False, startrow=1)
            ws = xw.sheets[name]
            ws["A1"] = t.get("title") or ""
            ws["A1"].font = Font(bold=True, size=12)
            for j, c in enumerate(df.columns, 1):
                ws.cell(row=2, column=j).font = Font(bold=True)
                width = max([len(str(c))] + [len(f"{v:,.2f}" if isinstance(v, float) else str(v))
                                             for v in df[c].head(200)])
                ws.column_dimensions[get_column_letter(j)].width = min(max(10, width + 2), 60)
                if pd.api.types.is_float_dtype(df[c]):
                    fmt = "0.00" if _PCT.search(str(c)) else "#,##0"
                    for r in range(3, len(df) + 3):
                        ws.cell(row=r, column=j).number_format = fmt
        if question:
            ws = xw.book.create_sheet("Question")
            ws["A1"], ws["A2"] = "Question", question
    return buf.getvalue()


def chart(ch: dict, key: str) -> None:
    import plotly.express as px
    import plotly.graph_objects as go

    df = pd.DataFrame(ch.get("rows") or [])
    if not len(df) or ch.get("x") not in df or ch.get("y") not in df:
        return
    x, y, kind, color = ch["x"], ch["y"], ch.get("kind", "bar"), ch.get("color")
    title = ch.get("title")
    if kind == "waterfall":
        meas = ["absolute" if str(s) in ("Opening", "Closing") else "relative" for s in df[x]]
        fig = go.Figure(go.Waterfall(x=df[x].astype(str), y=df[y], measure=meas,
                                     text=[f"{v:,.0f}" for v in df[y]], textposition="outside",
                                     connector=dict(line=dict(color="#d9d4e0")),
                                     increasing=dict(marker=dict(color=ERR)),
                                     decreasing=dict(marker=dict(color=OK)),
                                     totals=dict(marker=dict(color=PLUM))))
        lv, pts = 0.0, []
        for m, v in zip(meas, df[y]):
            lv = float(v) if m == "absolute" else lv + float(v)
            pts.append(lv)
        lo, hi = min(pts), max(pts)
        pad = max((hi - lo) * 0.2, 1.0)
        if lo - pad > 0:
            fig.update_yaxes(range=[lo - pad, hi + pad])
        h = 420
    elif kind == "line":
        fig = px.line(df, x=x, y=y, color=color, color_discrete_sequence=SEQ)
        h = 380
    elif kind == "stacked":
        fig = px.bar(df, x=x, y=y, color=color, barmode="stack", color_discrete_sequence=SEQ)
        h = 400
    elif kind == "pie":
        fig = px.pie(df, names=x, values=y, hole=0.5, color_discrete_sequence=SEQ)
        h = 340
    else:
        d = df.copy()
        d[x] = d[x].astype(str)
        horizontal = ch.get("horizontal") or len(d) > 8
        if ch.get("diverging"):
            colours = [ERR if v >= 0 else OK for v in d[y]]
        else:
            colours = [PLUM] * len(d)
        if horizontal:
            d = d.iloc[::-1]
            colours = colours[::-1]
        fig = px.bar(d, x=y if horizontal else x, y=x if horizontal else y,
                     orientation="h" if horizontal else "v")
        fig.update_traces(marker_color=colours, text=[f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.2f}" for v in d[y]],
                          textposition="outside", cliponaxis=False)
        h = max(260, 30 * len(d) + 90) if horizontal else 380
    nice = {"ecl": "ECL (QAR)", "exposure": "Exposure (QAR)", "change": "Change (QAR)",
            "amount": "QAR", "contracts": "Contracts", "customers": "Customers",
            "coverage": "Coverage %", "pd_pct": "PD %", "month": "Month", "ead": "EAD (QAR)"}
    fig.update_xaxes(title_text=nice.get(str(y if kind == "bar" and (ch.get("horizontal") or len(df) > 8) else x),
                                         str(y if kind == "bar" and (ch.get("horizontal") or len(df) > 8) else x)
                                         .replace("_", " ")))
    if kind != "pie":
        ylab = x if kind == "bar" and (ch.get("horizontal") or len(df) > 8) else y
        fig.update_yaxes(title_text=nice.get(str(ylab), str(ylab).replace("_", " ")))
    fig.update_layout(title=dict(text=title, font=dict(size=13)), height=h,
                      margin=dict(l=8, r=40, t=44 if title else 8, b=8),
                      plot_bgcolor="white", paper_bgcolor="white", font=dict(size=12, color="#4a5162"),
                      legend=dict(orientation="h", y=-0.18), separators=".,")
    fig.update_xaxes(gridcolor="#f4f2f7")
    fig.update_yaxes(gridcolor="#f4f2f7")
    st.plotly_chart(fig, use_container_width=True, key=key)


_DMATH = re.compile(r"\$\$(.+?)\$\$", re.S)
_ITEM = re.compile(r"^(\s*)(?:[-*•]|\d+[.)])\s+")


def tidy_math(text: str) -> str:
    """A formula the model wrote inside a sentence ("… factor. $$SF = …$$ This …")
    on a line of its own, centred, the way the methodology prints it; inside a
    numbered step it stays part of that step."""
    out = []
    for line in (text or "").split("\n"):
        if "$$" not in line or line.strip().startswith("$$") and line.strip().endswith("$$") \
                and line.strip().count("$$") == 2:
            out.append(line)
            continue
        m = _ITEM.match(line)
        pad = " " * (len(m.group(0)) if m else 0)
        parts = _DMATH.split(line)
        for k, part in enumerate(parts):
            if k % 2:                                     # a formula
                out += ["", f"{pad}$$", f"{pad}{part.strip()}", f"{pad}$$", ""]
            elif part.strip():
                out.append(part.rstrip() if k == 0 else f"{pad}{part.strip()}")
    return "\n".join(out)


def _urls(text: str) -> str:
    """A file in docs/regulatory is served by the backend; the answer names it
    regfile://<path>."""
    return (text or "").replace("regfile://", f"{api.BACKEND.rstrip('/')}/api/regulatory/file/")


def render(turn: dict, i: int, live: bool = False) -> None:
    st.markdown(tidy_math(_urls(turn["content"])))
    chk = turn.get("check") or {}
    if chk.get("removed"):
        st.caption(":material/fact_check: Parts of the reply that the run's data did not support "
                   "were removed. The table below is the run's own data.")
    if turn.get("chart"):
        chart(turn["chart"], key=f"as_chart_{i}")
    tables = turn.get("tables") or []
    for j, t in enumerate(tables):
        df = _frame(t)
        if not len(df):
            continue
        box = (st.expander(f"Data: {t.get('title') or 'table'}", icon=":material/table:")
               if t.get("collapsed") else st.container())
        with box:
            if not t.get("collapsed"):
                st.caption(t.get("title") or "")
            st.dataframe(df, hide_index=True, use_container_width=True,
                         column_config=_column_config(df), height=min(38 + 35 * len(df), 420),
                         key=f"as_tbl_{i}_{j}")
    docs = turn.get("docs") or []
    sections = [d for d in docs if d.get("kind", "section") == "section"]
    passages = [d for d in docs if d.get("kind") == "passage"]
    # a methodology answer: the document sections themselves, in full, each
    # with a link that opens the document there (in a new tab)
    for j, d in enumerate(sections):
        with st.container(border=True):
            url = _section_url(d.get("link"))
            st.markdown(f"**{d.get('title', '')} › {d.get('heading', '')}**"
                        + (f" &nbsp;·&nbsp; [Open in the document ↗]({url})" if url else ""))
            body = d.get("text") or ""
            if body.lstrip().startswith("#"):          # its heading is the line above
                body = body.lstrip().split("\n", 1)[1] if "\n" in body.lstrip() else ""
            _doc_text(body)
    # regulatory passages: folded, each with its link
    if passages:
        with st.expander(f"Passages ({len(passages)})", icon=":material/gavel:"):
            for j, d in enumerate(passages):
                url = _section_url(d.get("link")) or (
                    _urls("regfile://" + d["file"].removeprefix("docs/regulatory/")
                          + _page_anchor(d.get("heading"))) if d.get("file") else None)
                st.markdown(f"**{d.get('title', '')} › {d.get('heading', '')}**"
                            + (f" &nbsp;·&nbsp; [Open ↗]({url})" if url else ""))
                if d.get("file"):
                    st.text((d.get("text") or "")[:3000])
                else:
                    _doc_text(d.get("text") or "")
    srcs = turn.get("sources") or []
    if srcs:
        st.markdown("**Sources** &nbsp; " + " &nbsp;·&nbsp; ".join(
            f"[{s_['label']} ↗]({_urls(s_['url'])})" for s_ in srcs))
    ask = turn.get("ask")
    if ask and ask.get("options") and i == len(history) - 1:
        cols = st.columns(min(len(ask["options"]), 3))
        for k, opt in enumerate(ask["options"]):
            cols[k % len(cols)].button(opt, key=f"as_opt_{i}_{k}", use_container_width=True,
                                       on_click=_queue, args=(opt,))
    if turn.get("followups") and i == len(history) - 1 and not ask:
        st.caption("Ask next")
        cols = st.columns(len(turn["followups"]))
        for k, f in enumerate(turn["followups"]):
            cols[k].button(f, key=f"as_fu_{i}_{k}", use_container_width=True,
                           on_click=_queue, args=(f,))
    if turn.get("steps"):
        with st.expander(f"How this was looked up ({len(turn['steps'])})", icon=":material/search:"):
            st.dataframe(pd.DataFrame([{"lookup": s["id"], "tool": s["tool"],
                                        "arguments": str(s.get("args") or ""),
                                        "worked": "yes" if s.get("ok") else "no"} for s in turn["steps"]]),
                         hide_index=True, use_container_width=True, key=f"as_steps_{i}")


def _doc_text(text: str) -> None:
    """A document section as the Help page draws it: headings one level down,
    formulas rendered, pictures from docs/."""
    import docs_view
    docs_view.render_section(text)


def _section_url(link: dict | None) -> str | None:
    """/help_ecl?ch=..&sec=..: a Help document at a section."""
    from urllib.parse import quote
    if not link or not link.get("page"):
        return None
    stem = link["page"].rsplit("/", 1)[-1].removesuffix(".py")
    q = "&".join(f"{k}={quote(str(v))}" for k, v in (("ch", link.get("ch")), ("sec", link.get("sec"))) if v)
    return f"/{stem}" + (f"?{q}" if q else "")


def _page_anchor(heading) -> str:
    m = re.search(r"(\d+)", str(heading or ""))
    return f"#page={m.group(1)}" if m else ""


def _open_link(link: dict | None, key: str) -> None:
    """A button that opens the Help page at the section."""
    if not link:
        return
    try:
        st.page_link(link["page"], label=f"Open {link.get('label') or 'in Help'}",
                     icon=":material/open_in_new:",
                     query_params={k: v for k, v in (("ch", link.get("ch")), ("sec", link.get("sec"))) if v})
    except Exception:                       # page not registered (a test, an old app)
        st.caption(link.get("label") or "")


def _file_button(rel: str, key: str) -> None:
    """Download the regulatory text a passage comes from (it is on this
    machine, in docs/regulatory)."""
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / rel
    if p.is_file():
        st.download_button(f"Download {p.name}", p.read_bytes(), file_name=p.name, key=key,
                           icon=":material/download:")


def _queue(q: str) -> None:
    S["assistant_pending"] = q


# ------------------------------------------------------------------- page --
c1, c3, c2 = st.columns([4.6, 1.6, 1], vertical_alignment="bottom")
c1.caption(f"Focus: {run_id or 'the most recent run'} · answers use the same figures as the pages, "
           "the documents under Help and the engine's code")
model_id = None
if MODELS:
    ids = [m["id"] for m in MODELS]
    if S.get("assistant_model") not in ids:
        default = next((m["id"] for m in MODELS if m.get("default") and m.get("available")), None)
        S["assistant_model"] = default or (usable[0]["id"] if usable else ids[0])
    label = {m["id"]: m["label"] + ("" if m.get("available") else " (needs key)") for m in MODELS}
    model_id = c3.selectbox("Model", ids, format_func=lambda i: label[i], key="assistant_model",
                            label_visibility="collapsed")
    chosen = next(m for m in MODELS if m["id"] == model_id)
    dflt = next((m for m in MODELS if m.get("default")), None)
    if not chosen.get("available"):
        st.warning(chosen.get("reason") or "This model cannot be used now.", icon=":material/key:")
    elif dflt and not dflt.get("available") and dflt["id"] != model_id:
        st.caption(f":material/key: {dflt['label']} is the default but cannot be used yet: {dflt.get('reason')} "
                   f"Until then the assistant uses {chosen['label']}.")
if c2.button("New chat", use_container_width=True, disabled=not history, icon=":material/refresh:"):
    S["assistant_history"] = []
    st.rerun()
model_ok = not MODELS or next((m.get("available") for m in MODELS if m["id"] == model_id), True)

if not history:
    st.markdown("##### Try")
    cols = st.columns(3)
    for k, q in enumerate(EXAMPLES):
        cols[k % 3].button(q, key=f"as_ex_{k}", use_container_width=True, on_click=_queue, args=(q,))

for i, turn in enumerate(history):
    with st.chat_message(turn["role"]):
        if turn["role"] == "user":
            st.markdown(turn["content"])
        else:
            render(turn, i)

typed = st.chat_input("Ask about a run, the model, the config or how the tool works", disabled=not model_ok)
question = (typed or S.pop("assistant_pending", None)) if model_ok else None
if question:
    history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    def _ctx(t: dict) -> str:
        """An earlier answer as the model sees it again: the text, plus which
        lookups gave it, so "now by stage" can build on the last question."""
        if t["role"] != "assistant" or not t.get("steps"):
            return t["content"]
        looks = "; ".join(f"{x['tool']}({', '.join(f'{k}={v}' for k, v in (x.get('args') or {}).items())})"
                          for x in t["steps"])
        return f"{t['content']}\n[lookups used: {looks}]"

    plain = [{"role": t["role"], "content": _ctx(t)} for t in history[:-1]]
    with st.chat_message("assistant"):
        with st.spinner("Looking it up…"):
            try:
                r = api.assistant_ask(question, run_id, plain, model_id)
            except api.BackendError as e:
                r = {"ok": False, "text": str(e)}
    history.append({"role": "assistant", "content": r.get("text") or "", "question": question,
                    "tables": r.get("tables") or [], "chart": r.get("chart"),
                    "cites": r.get("cites") or [], "ask": r.get("ask"),
                    "followups": r.get("followups") or [], "steps": r.get("steps") or [],
                    "check": r.get("check") or {}, "docs": r.get("docs") or [],
                    "sources": r.get("sources") or []})
    st.rerun()
