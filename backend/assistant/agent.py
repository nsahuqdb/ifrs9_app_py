"""The loop: ask, look something up, ask again, answer.

The model never sees a database. It sees a system prompt, and a protocol in
which its only two moves are "call a tool" and "answer". Everything factual it
can say therefore came back from a tool in this conversation, which is what
makes the grounding rule enforceable instead of aspirational.

Charts are referenced, not retyped. When the model wants to show one it names
the tool observation to plot, and the app draws that tool's own numbers -- so
a chart cannot disagree with the table above it.
"""
from __future__ import annotations

import json
import re

from .client import AssistantError, chat
from .config import AssistantConfig, load_config
from .tools import TOOL_CATALOGUE, execute_tool


def _trim(text: str, n: int) -> str:
    text = str(text)
    return text if len(text) <= n else text[: n - 1] + "…"


def seed_context(run_id: str | None = None,
                 max_chars: int = 6000) -> str:
    """What the assistant knows before it asks anything.

    Enough to answer "which runs are there" without a round trip, and enough
    to name a default run. Everything else it has to fetch.
    """
    parts = [execute_tool("list_runs").get("summary", "")]
    if run_id:
        parts.append(execute_tool("list_files", {"run_id": run_id})
                     .get("summary", ""))
    return _trim("\n\n".join(p for p in parts if p), max_chars)


SYSTEM = """\
You are the IFRS 9 ECL assistant, embedded in Qatar Development Bank's
provisioning app. You answer questions about runs, configuration, governance,
the credit-risk methodology, and the run outputs — stages, ratings, exposures,
PD term structures, collateral, provisions — including comparing one run with
another.

You call TOOLS to fetch real data. The tools are:
{tools}

PROTOCOL. Every message you send is a single JSON object and nothing else: no
prose around it, no markdown fences.
  To call a tool:  {{"action":"tool","tool":"<name>","args":{{...}}}}
  To answer:       {{"action":"final","answer":"<markdown>","chart_ref":"<tool_id or null>"}}
After each tool call you get an OBSERVATION with the result and a tool_id such
as t1. Chain as many calls as you need, then answer. To show a chart, set
chart_ref to the tool_id of the observation you want plotted — the app draws
it from that tool's own numbers, so never retype numbers into a chart. Use
null when no chart helps.

Emit strict JSON. Do not backslash-escape underscores: write
VAR_NON_OIL_GDP_GROWTH, never VAR\\_NON_OIL_GDP_GROWTH. Only \\n, \\" and \\\\
are legal escapes. Put markdown inside the answer string, not around the JSON.

RULES
1. Ground every factual claim in a tool observation or the context below.
   Never invent a run id, a number, a name, a date or an approval. If
   something is missing, say so and name the page or file that would have it.
2. Configuration is not in a run's outputs. For anything about the model —
   coefficients, intercepts, weights, MEVs, the anchor PD, horizons — call
   model_spec, which reads the run's frozen config and needs no aggregation.
   Never claim a coefficient is unavailable without calling it first.
3. For validation, call validation_results.
4. Put data in compact markdown tables. Lead with the direct answer, then the
   detail behind it.
5. Default to {focus} when a question needs a run and names none. For a
   comparison, pick the two runs from the run list.
6. This engine computes the provision itself: Cla Amount Onbal in
   FinalEclReport.csv is the ECL per contract. Stage 3 is booked at the full
   outstanding balance, which is QDB's basis and deliberately differs from
   LIC's zero, and the provision is capped at the on-balance exposure. Say so
   when a reconciliation against a LIC extract comes up.
7. You are read-only. You cannot start a run, edit config, or approve
   anything. If asked to, name the page that does it.

CONTEXT
{seed}"""


def _system_prompt(seed: str, run_id: str | None) -> str:
    focus = f"run '{run_id}'" if run_id else "the most recent run"
    return SYSTEM.format(tools=TOOL_CATALOGUE, focus=focus, seed=seed)


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
# A markdown-trained model writes \_ inside JSON strings, which is not a legal
# escape and makes the whole object unparseable. Repairing it is the difference
# between an answer and a shrug.
_BAD_ESCAPE = re.compile(r'\\(?!["\\/bfnrtu])')


def extract_json(text: str) -> dict | None:
    """The first well-formed JSON object in a reply, fences and slips allowed."""
    if not text:
        return None
    candidates = _FENCE.findall(text) or []
    start = text.find("{")
    if start >= 0:
        candidates.append(text[start:])
    for raw in candidates:
        raw = raw.strip()
        for attempt in (raw, _BAD_ESCAPE.sub("", raw)):
            for end in range(len(attempt), max(len(attempt) - 4000, 0), -1):
                if attempt[end - 1: end] != "}":
                    continue
                try:
                    got = json.loads(attempt[:end])
                except json.JSONDecodeError:
                    continue
                if isinstance(got, dict):
                    return got
    return None


def answer(question: str, history: list[dict] | None = None,
           run_id: str | None = None,
           cfg: AssistantConfig | None = None) -> dict:
    """One question, answered. Returns ``{ok, text, chart, steps}``.

    ``steps`` is the tool trail: which tool, with which arguments, and whether
    it succeeded. It is shown in the app, because an assistant over regulatory
    numbers should be auditable — a user who cannot see where a figure came
    from has to take it on faith, and that is exactly what a provision cannot
    be taken on.
    """
    cfg = cfg or load_config()
    reason = cfg.unavailable_reason()
    if reason:
        return {"ok": False, "text": reason, "chart": None, "steps": []}

    history = list(history or [])
    if len(history) > cfg.max_history_turns * 2:
        history = history[-cfg.max_history_turns * 2:]

    seed = seed_context(run_id, max_chars=cfg.max_context_chars // 4)
    convo = ([{"role": "system", "content": _system_prompt(seed, run_id)}]
             + history + [{"role": "user", "content": question}])

    charts: dict[str, dict] = {}
    steps: list[dict] = []
    calls = 0

    def finish(parsed: dict, fallback: str) -> dict:
        ref = parsed.get("chart_ref") if parsed else None
        return {"ok": True,
                "text": (parsed or {}).get("answer") or fallback,
                "chart": charts.get(str(ref)) if ref else None,
                "steps": steps}

    while True:
        try:
            raw = chat(convo, cfg)
        except AssistantError as exc:
            return {"ok": False, "text": str(exc), "chart": None, "steps": steps}

        parsed = extract_json(raw)
        if parsed is None:
            # Not JSON: take it as the answer rather than arguing about format.
            return {"ok": True, "text": raw, "chart": None, "steps": steps}

        action = parsed.get("action") or (
            "final" if "answer" in parsed else "tool" if "tool" in parsed else "")

        if action == "final":
            return finish(parsed, "The assistant returned an empty answer.")

        if action != "tool":
            return {"ok": True, "text": raw, "chart": None, "steps": steps}

        if calls >= cfg.max_tool_calls:
            convo += [
                {"role": "assistant", "content": raw},
                {"role": "user",
                 "content": "Tool-call limit reached. Answer now with "
                            'action="final" and what you already have.'},
            ]
            try:
                last = chat(convo, cfg)
            except AssistantError as exc:
                return {"ok": False, "text": str(exc), "chart": None,
                        "steps": steps}
            return finish(extract_json(last) or {}, last)

        calls += 1
        tool_id = f"t{calls}"
        name = parsed.get("tool") or ""
        args = parsed.get("args") or {}
        if run_id and isinstance(args, dict) and "run_id" in args \
                and not args.get("run_id"):
            args["run_id"] = run_id
        result = execute_tool(name, args if isinstance(args, dict) else {})
        steps.append({"id": tool_id, "tool": name, "args": args,
                      "ok": bool(result.get("ok"))})
        if result.get("chart"):
            charts[tool_id] = result["chart"]

        convo += [
            {"role": "assistant", "content": raw},
            {"role": "user",
             "content": f"OBSERVATION (tool={name}, tool_id={tool_id}):\n"
                        f"{_trim(result.get('summary', '(no result)'), 6000)}"},
        ]
