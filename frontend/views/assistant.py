"""Ask questions about the runs in plain language.

The assistant is read-only and grounded: it can only see what its tools hand
it, so every figure it quotes came back from a real run in this conversation.
The tool trail under each answer shows exactly which — a provision figure
nobody can trace is one nobody should rely on.
"""
import pandas as pd
import streamlit as st

import api
from ui import bar, caption, fmt_table, guard, page_setup

run_id = st.session_state.get("run_id")
page_setup("Assistant", "Questions about the runs, answered from the runs")

with guard():
    status = api.assistant_status()

if not status.get("available"):
    st.info(status.get("reason", "The assistant is not configured."), icon="🔌")
    st.markdown(f"""
It needs an OpenAI-compatible chat endpoint. Two settings turn it on, either
in the app's `config.yml` under an `assistant:` block or in the environment:

```yaml
assistant:
  enabled: true
  endpoint: https://your-gateway/v1/chat/completions
  model: your-model-name
  api_key_env: {status.get('api_key_env', 'IFRS9_LLM_API_KEY')}
```

```bash
export IFRS9_LLM_ENDPOINT=https://your-gateway/v1/chat/completions
export IFRS9_LLM_MODEL=your-model-name
export {status.get('api_key_env', 'IFRS9_LLM_API_KEY')}=…        # only if the gateway needs one
```

The key is never read from the config file — only from the environment
variable named there — so the config can be committed, frozen into a run and
pasted into a ticket without carrying a credential.
""")
    with st.expander("What it would be able to look at"):
        caption("These ten tools are the assistant's whole view of the data. "
                "It cannot reach anything else, which is what makes "
                "\"every claim is grounded\" a property rather than a hope.")
        st.write("\n".join(f"- `{t}`" for t in status.get("tools", [])))
    st.stop()

caption(f"{status['model']} · at most {status['max_tool_calls']} lookups per "
        f"question · focused on {run_id or 'the most recent run'}")

if "assistant_history" not in st.session_state:
    st.session_state["assistant_history"] = []
history = st.session_state["assistant_history"]

c1, c2 = st.columns([6, 1])
with c2:
    if st.button("Clear", use_container_width=True, disabled=not history):
        st.session_state["assistant_history"] = []
        st.rerun()

if not history:
    # caption() renders HTML, not markdown, so italics are a tag here.
    caption("Try: <em>which portfolio moved most between the two runs?</em> · "
            "<em>what are the MEV coefficients?</em> · <em>which validation "
            "checks failed?</em> · <em>show the stage split by portfolio</em>")

for turn in history:
    with st.chat_message(turn["role"]):
        st.markdown(turn["content"])
        if turn.get("chart"):
            ch = turn["chart"]
            frame = pd.DataFrame(ch["rows"])
            if len(frame):
                bar(frame, ch["x"], ch["y"], title=ch.get("title"))
        if turn.get("steps"):
            with st.expander(f"{len(turn['steps'])} lookups"):
                st.dataframe(pd.DataFrame(turn["steps"]),
                             use_container_width=True, hide_index=True)

question = st.chat_input("Ask about a run, the config, or the model")
if question:
    st.session_state["assistant_history"].append(
        {"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    plain = [{"role": t["role"], "content": t["content"]}
             for t in st.session_state["assistant_history"]][:-1]
    with st.chat_message("assistant"), st.spinner("Looking it up…"):
        try:
            r = api.assistant_ask(question, run_id, plain)
        except api.BackendError as e:
            r = {"ok": False, "text": str(e), "chart": None, "steps": []}

        st.markdown(r["text"])
        if r.get("chart"):
            frame = pd.DataFrame(r["chart"]["rows"])
            if len(frame):
                bar(frame, r["chart"]["x"], r["chart"]["y"],
                    title=r["chart"].get("title"))
        if r.get("steps"):
            with st.expander(f"{len(r['steps'])} lookups"):
                st.dataframe(pd.DataFrame(r["steps"]),
                             use_container_width=True, hide_index=True)

    st.session_state["assistant_history"].append({
        "role": "assistant", "content": r["text"],
        "chart": r.get("chart"), "steps": r.get("steps", [])})
