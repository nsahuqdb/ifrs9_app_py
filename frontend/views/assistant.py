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

if not status.get("available"):
    st.info(status.get("reason", "The assistant is not configured."), icon="🔌")
    st.markdown(f"""
It needs an OpenAI-compatible chat endpoint, set in the app's `config.yml`
under `assistant:` or in the environment:

```yaml
assistant:
  enabled: true
  endpoint: https://your-gateway/v1/chat/completions
  model: your-model-name
  api_key_env: {status.get('api_key_env', 'IFRS9_LLM_API_KEY')}
```

The key is read only from the environment variable named there.
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


def render(turn: dict, i: int, live: bool = False) -> None:
    st.markdown(turn["content"])
    chk = turn.get("check") or {}
    if chk.get("removed"):
        st.caption(":material/fact_check: Some figures or customers in the reply were not in the "
                   "data the lookup returned and were removed. The table below is the run's own data.")
    if turn.get("chart"):
        chart(turn["chart"], key=f"as_chart_{i}")
    tables = turn.get("tables") or []
    for j, t in enumerate(tables):
        df = _frame(t)
        if not len(df):
            continue
        st.caption(t.get("title") or "")
        st.dataframe(df, hide_index=True, use_container_width=True,
                     column_config=_column_config(df), height=min(38 + 35 * len(df), 420),
                     key=f"as_tbl_{i}_{j}")
    if tables:
        st.download_button("Download as Excel", to_excel(tables, turn.get("question", "")),
                           file_name=f"assistant_answer_{i}.xlsx", key=f"as_xl_{i}",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           icon=":material/download:")
    if turn.get("cites"):
        with st.expander(f"Sources ({len(turn['cites'])})", icon=":material/menu_book:"):
            for c in turn["cites"]:
                st.markdown(f"- **[{c['id']}]** {c['label']}")
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


def _queue(q: str) -> None:
    S["assistant_pending"] = q


# ------------------------------------------------------------------- page --
c1, c2 = st.columns([6, 1])
c1.caption(f"Focus: {run_id or 'the most recent run'} · answers use the same figures as the pages, "
           "the documents under Help and the engine's code")
if c2.button("New chat", use_container_width=True, disabled=not history, icon=":material/refresh:"):
    S["assistant_history"] = []
    st.rerun()

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

typed = st.chat_input("Ask about a run, the model, the config or how the tool works")
question = typed or S.pop("assistant_pending", None)
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
                r = api.assistant_ask(question, run_id, plain)
            except api.BackendError as e:
                r = {"ok": False, "text": str(e)}
    history.append({"role": "assistant", "content": r.get("text") or "", "question": question,
                    "tables": r.get("tables") or [], "chart": r.get("chart"),
                    "cites": r.get("cites") or [], "ask": r.get("ask"),
                    "followups": r.get("followups") or [], "steps": r.get("steps") or [],
                    "check": r.get("check") or {}})
    st.rerun()
