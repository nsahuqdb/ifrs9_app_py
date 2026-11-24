"""The loop: understand, look up, answer -- or ask.

The model never sees a database. It sees a system prompt, the runs and the
focus run's headline, and a protocol with three moves:

* ``tool``  -- call one of the tools and read its OBSERVATION;
* ``ask``   -- ask the user a short clarifying question, with options;
* ``final`` -- answer in markdown, naming which tool results to show as
  tables and which one to chart, and which passages it cites.

Tables and charts are referenced, never retyped: the app draws the tool's own
rows, so a chart cannot disagree with the table above it, and every table can
be downloaded to Excel exactly as computed. The prompt is short and carries
worked examples, because the deployment's model is a 12B model that follows
examples better than long rules.
"""
from __future__ import annotations

import dataclasses
import json
import re

from .client import AssistantError, chat
from .ground import Facts, denies, remove, strip_tables, tool_talk, unsupported
from .router import looks_like_data, plan as route
from .config import AssistantConfig, load_config
from .semantic import CATALOGUE, TOOLS as SEMANTIC, USED_RUNS, resolve_run, run_label
from .tools import execute_tool as raw_tool


def _trim(text: str, n: int) -> str:
    text = str(text)
    return text if len(text) <= n else text[: n - 1] + "…"


# Raw output-file tools stay available for anything the semantic tools miss.
RAW = ("list_files", "describe_file", "aggregate", "filter_rows", "column_stats", "diff_files")
CATALOGUE_ALL = CATALOGUE + """
RAW OUTPUT FILES (only when nothing above fits)
- list_files(run) · describe_file(run, file) · aggregate(run, file, group_by, measure, fn) · filter_rows(run, file, where, columns, limit)"""


def execute(name: str, args: dict | None, focus: str | None) -> dict:
    """One tool by name, noting which runs it read (``runs_used``)."""
    tok = USED_RUNS.set([])
    try:
        res = _execute(name, args, focus)
    finally:
        used = USED_RUNS.get() or []
        USED_RUNS.reset(tok)
    if isinstance(res, dict) and res.get("ok") and used:
        res["runs_used"] = list(used)
    return res


def _execute(name: str, args: dict | None, focus: str | None) -> dict:
    """One tool by name. Semantic tools get the focus run; a failure is a
    result the model can read, never an exception."""
    args = dict(args or {})
    name = str(name or "").strip()
    # a small model names tools loosely: map the usual slips
    alias = {"summary": "overview", "headline": "overview", "stage_split": "breakdown",
             "group_by": "breakdown", "split": "breakdown", "search": "search_docs",
             "docs": "search_docs", "search_code": "search_docs", "code": "read_code",
             "list_runs": "runs", "model_spec": "model", "validation_results": "validation",
             "bridge": "movement", "waterfall": "movement", "customers": "top",
             "top_customers": "top", "pd_curves": "pd_curve", "config": "config_file"}
    if name in alias and not (name in ("list_runs", "model_spec", "validation_results")
                              and "file" in args):
        if name == "search_code":
            args.setdefault("scope", "code")
        if name == "stage_split":
            args.setdefault("by", "stage")
        name = alias[name]
    if name == "compare_runs" and "file" not in args:
        name = "compare"
    if name in SEMANTIC:
        # the model sometimes says run_id, sometimes run: take either
        for k in ("run", "run_id_b"):
            if k in args and "run_id" not in args and name not in ("compare", "movement", "migration"):
                args["run_id"] = args.pop(k)
        if name in ("compare", "movement", "migration"):
            args.setdefault("run_a", args.pop("run_id_a", None) or args.pop("from", None) or "previous")
            if "run_id_b" in args or "to" in args:
                args["run_b"] = args.pop("run_id_b", None) or args.pop("to", None)
        try:
            return SEMANTIC[name](focus=focus, **args)
        except TypeError as exc:
            return {"ok": False, "summary": f"{name} does not take these arguments: {exc}"}
        except Exception as exc:
            return {"ok": False, "summary": f"{name} failed: {getattr(exc, 'detail', exc)}"}
    if name in RAW or name in ("list_runs", "model_spec", "validation_results", "compare_runs"):
        if "run" in args and "run_id" not in args:
            args["run_id"] = args.pop("run")
        if "run_id" in args:
            rid, _ = resolve_run(args.get("run_id"), focus)
            args["run_id"] = rid or args["run_id"]
        elif name not in ("list_runs", "compare_runs", "diff_files"):
            args["run_id"] = focus
        return raw_tool(name, args)
    return {"ok": False, "summary": f"There is no tool called {name!r}. Use one of: "
                                    + ", ".join(list(SEMANTIC) + list(RAW)) + "."}


def _portfolios(run_id: str | None) -> list[str]:
    """The focus run's portfolio names, so a question naming one is filtered."""
    try:
        from .semantic import _report
        rid, _ = resolve_run(None, run_id)
        if not rid:
            return []
        d = _report(rid)
        return sorted({str(p) for p in d["portfolio"].dropna().unique()}) if "portfolio" in d else []
    except Exception:
        return []


def seed_context(run_id: str | None = None, max_chars: int = 6000) -> str:
    """What the assistant knows before it asks anything: the runs, and the
    focus run's headline -- enough to answer the commonest questions with no
    lookup at all, and to name runs correctly in every other."""
    parts = []
    r = SEMANTIC["runs"](focus=run_id)
    if r.get("ok"):
        parts.append("RUNS\n" + r["summary"])
    rid, _ = resolve_run(run_id, run_id)
    if rid:
        o = SEMANTIC["overview"](run_id=rid, focus=rid)
        if o.get("ok"):
            parts.append(f"FOCUS RUN {rid}\n" + o["summary"])
    return _trim("\n\n".join(parts), max_chars)


SYSTEM = """\
You are the assistant of Qatar Development Bank's IFRS 9 ECL tool. You help risk and finance staff with \
the runs (provision, stages, ratings, exposure, PD, LGD, collateral, scenarios, movement between runs), \
the model and configuration, governance (approvals, overrides, overlays, versions, audit), and how the \
tool and the methodology work.

Reply with ONE JSON object and nothing else. Three moves:
  {{"action":"tool","tool":"<name>","args":{{...}}}}
  {{"action":"ask","question":"<short question>","options":["<option>", "..."]}}
  {{"action":"final","answer":"<markdown>","show":["t1"],"chart":"t1","cite":["k12"],"followups":["<question>", "..."]}}
After a tool call you receive OBSERVATION tN. "show" lists the observations to display as tables (the app \
draws them, with an Excel download); "chart" is the observation to plot, or null; "cite" lists passage ids \
(k…) from explain, search_docs or read_code that support the answer; "followups" are 2–3 short next questions.

TOOLS
{tools}

RULES
1. Every number, name, date or approval you state comes from CONTEXT or an OBSERVATION. Never guess. \
If something is not available, say so and name the page that has it.
2. Use the CONTEXT first: it already has the runs and the focus run's totals by stage and portfolio.
3. Ask instead of guessing when the question is ambiguous in a way that changes the answer: which run(s), \
which customer of several matches, which measure ("biggest" by ECL or exposure?). Do not ask when a \
sensible default exists: focus run = {focus}; comparisons = previous run → focus run; measure = ECL.
4. For how / what-is / why questions about the METHOD or the TOOL, call explain(query). The app shows \
the sections it returns IN FULL under your answer -- text, formulas, worked examples -- each with a link \
that opens the document at that section. Your answer is the guide on top, in plain words: what the answer \
is, then the steps in order, saying for each step which input it uses and what comes out of it. If the \
sections describe more than one version (internal and external scale, lending and investments, Stage 1/2 \
and Stage 3) and the user did not name one, cover EACH under its own bold heading. Do NOT write formulas \
or LaTeX: the sections show them exactly. Say only what the sections say, with their own names for \
things: no definitions, horizons or claims of your own. Put the section id in square brackets where you \
use it, e.g. [k19]: the app turns it into a link. Never cite or mention code unless the user asked about \
the code (then search_docs with scope "code" or read_code).
5a. For a question that compares QDB with a regulation (Basel, QCB, IFRS 9, EBA, Bank of England, Fed, \
FINMA) or asks what a regulation says: use benchmark(topic) and regulation(query). For each item asked \
about, state QDB's value, the regulator's value with its paragraph (e.g. CRE22.49, B5.5.37, pack slide 84) \
and whether QDB is higher, lower or the same, i.e. more or less conservative. Say that Basel values are \
capital rules, not provisioning rules, when you compare with them. If a QCB value is not in an \
observation, say it has to be read in the QCB circular and whether the circular is in the regulatory \
folder. Never state a regulatory number that no observation gives.
5. For a question about the RUN's figures: the direct answer first (one or two sentences with the key \
figures), then at most three bullets on what drives it -- for a "why", name the main reason or step from \
the observation with its figure (a movement step, a stage reason, a trigger). Do not retype a table that \
you list in "show"; refer to it. Amounts in QAR with thousands separators; say "mln" for millions when \
rounding.
6. The app decides whether a result is drawn as a table, a chart or both; you only list the observations \
in "show".
7. You are read-only: you cannot run, edit or approve. Say which page does it (e.g. Runs → Run the \
pipeline, Governance → Management overlay, Runs → Approval queue).
8. NEVER type a table, a list of customers with amounts, or rows of figures in "answer". The app draws \
the table from the lookup itself; you name it in "show". Mention at most the one or two key figures, copied \
exactly as the observation shows them. Every answer is checked: a figure or customer that is in no \
observation is removed before the user sees it.
9. If a lookup failed or returned nothing, say so plainly. Do not fill the gap.
10. If the user says a figure is wrong, do the lookup again and show its table. Do not apologise at length, \
and never claim to report, escalate, halt or contact anyone: you cannot.
11. Glossary: ECL = provision (Cla Amount Onbal); coverage = ECL ÷ exposure; Stage 3 is provisioned at 100% \
of the balance; booked ECL uses probability-weighted PDs; overlay = management adjustment added after the model.

EXAMPLES
User: show the stage split by portfolio
{{"action":"tool","tool":"breakdown","args":{{"by":["portfolio","stage"],"measure":"ecl"}}}}
OBSERVATION t1 …
{{"action":"final","answer":"<portfolio from t1> carries most of the provision (… of …). Stage 3 is … of the total.","show":["t1"],"chart":"t1","cite":[],"followups":["Which customers drive Stage 3?","How did this change since the previous run?"]}}

User: which portfolio moved most between the two runs?
{{"action":"tool","tool":"movement","args":{{"run_a":"previous","level":"portfolio"}}}}
OBSERVATION t1 …
{{"action":"final","answer":"**<portfolio from t1>** moved most: ECL fell by … (…%), mainly … (…).","show":["t1"],"chart":"t1","cite":[],"followups":["Show that portfolio's movement step by step"]}}

User: how is the PD calculated?
{{"action":"tool","tool":"explain","args":{{"query":"how is the PD calculated"}}}}
OBSERVATION t1 … sections k19 (internal scale) and k22 (external scale) …
{{"action":"final","answer":"<one sentence answer>\\n\\n**Internal scale (lending)**\\n1. <step in plain words, the input it uses and what it gives> [k19]\\n2. …\\n\\n**External scale (investments)**\\n1. <step> [k22]\\n…","show":[],"cite":["k19","k22"],"followups":["How are the scenario weights set?"]}}

User: what is the ECL of <a name>?
{{"action":"tool","tool":"customer","args":{{"query":"<the name>"}}}}
OBSERVATION t1 … several customers match …
{{"action":"ask","question":"Several customers match. Which one?","options":["<id · name exactly as t1 lists it>","<id · name exactly as t1 lists it>"]}}

User: top 5 customers in stage 2
{{"action":"tool","tool":"top","args":{{"by":"customer","measure":"ecl","n":5,"filters":{{"stage":2}}}}}}
OBSERVATION t1 …
{{"action":"final","answer":"The five largest Stage 2 customers are in the table; together they hold … of Stage 2 ECL (figure from t1).","show":["t1"],"chart":"t1","cite":[],"followups":["Why are they in Stage 2?"]}}
(The "…" above stand for figures you copy from the observation. Never use names, ids or figures from \
these examples: they are placeholders.)

CONTEXT
{seed}"""


def _system_prompt(seed: str, run_id: str | None) -> str:
    focus = run_id or "the most recent run"
    return SYSTEM.format(tools=CATALOGUE_ALL, focus=focus, seed=seed)


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
# A markdown-trained model writes \_ inside JSON strings, which is not a legal
# escape and makes the whole object unparseable. Repairing it is the
# difference between an answer and a shrug.
_BAD_ESCAPE = re.compile(r'\\(?!["\\/bfnrtu])')


# LaTeX commands whose first letter is also a JSON escape (\b \f \n \r \t):
# a model writing "\frac" or "\right" in a JSON string means the command, not
# a form feed or a carriage return.
_LATEX_JSON_CLASH = set("""beta bar big Big bigg bigl bigr binom bmod boldsymbol bullet backslash bot bf
frac forall flat nu nabla neq ne not notin nolimits ni nmid newline right rho rangle rceil rfloor rm
rbrace rbrack text textbf textit textrm tfrac theta tau times to tilde top tan tanh triangle tt""".split())
_WORD = re.compile(r"[A-Za-z]+")


def latex_safe(raw: str) -> str:
    r"""A model's JSON with its LaTeX kept: every backslash that starts a LaTeX
    command or symbol is doubled, so json.loads gives back "\frac", "\Phi",
    "\," instead of a form feed, a dropped letter or an error. Real JSON
    escapes (\n, \", \\, \u00e9 ...) are left as they are."""
    out, i, n = [], 0, len(raw)
    while i < n:
        c = raw[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        nxt = raw[i + 1] if i + 1 < n else ""
        if nxt in ('"', "\\", "/"):
            out.append(raw[i:i + 2])
            i += 2
            continue
        m = _WORD.match(raw, i + 1)
        if m and m.group(0) in _LATEX_JSON_CLASH:
            out.append("\\\\" + m.group(0))
            i = m.end()
            continue
        if nxt and nxt in "bfnrt":
            out.append(raw[i:i + 2])
            i += 2
            continue
        if nxt in "_*#`":                   # a Markdown escape (model\_spec): the character
            out.append(nxt)
            i += 2
            continue
        if nxt == "u" and re.match(r"[0-9a-fA-F]{4}", raw[i + 2:i + 6]):
            out.append(raw[i:i + 6])
            i += 6
            continue
        out.append("\\\\")              # \Phi, \sigma, \, ... : the backslash itself
        i += 1
    return "".join(out)


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
        for attempt in (latex_safe(raw), raw, _BAD_ESCAPE.sub("", raw),
                        # literal newlines inside strings: common, and illegal
                        re.sub(r'(?<!\\)\n', r'\\n', _BAD_ESCAPE.sub("", raw))):
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


_DATA_WORDS = re.compile(r"\b(chart|plot|graph|visual|trend|curve)\b", re.I)


def _as_list(v) -> list:
    if v is None or v == "" or v is False:
        return []
    return v if isinstance(v, list) else [v]


# How each lookup is best shown when the user has not said: "both" a chart
# with its table, "chart" with the table folded underneath, "table" alone,
# "auto" (a chart when a handful of groups are compared, else the table).
VIEW = {"movement": "both", "compare": "both", "staging": "both", "scenarios": "both",
        "migration": "both", "overview": "both", "breakdown": "auto", "pd_curve": "chart",
        "concentration": "both", "top": "table", "stage_moves": "table", "customer": "table",
        "stage_reason": "table", "validation": "table", "model": "table", "run_info": "table",
        "runs": "table", "config_file": "table", "data_quality": "table", "audit": "table",
        "benchmark": "table", "reg_documents": "table"}
_WANT_CHART = re.compile(r"\b(chart|plot|graph|visual\w*|draw|diagram|trend|curve|waterfall|pie|bars?)\b", re.I)
_WANT_TABLE = re.compile(r"\b(table|tabular|in rows|spreadsheet|excel)\b", re.I)
_WANT_CODE = re.compile(r"\b(code|function|python|source|implementation|implemented|script|module)\b", re.I)


def present(question: str, res: dict) -> tuple[str, bool]:
    """(how to show a lookup, whether its chart is drawn): what the user
    asked for, else what suits the result."""
    has_chart = bool(res.get("chart") and (res["chart"].get("rows") or []))
    chart_asked, table_asked = bool(_WANT_CHART.search(question or "")), bool(_WANT_TABLE.search(question or ""))
    if chart_asked and has_chart:
        return ("both" if table_asked else "chart"), True
    if table_asked:
        return "table", False
    mode = VIEW.get(res.get("tool", ""), "table")
    if mode == "auto":
        n = len((res.get("chart") or {}).get("rows") or [])
        mode = "both" if 2 <= n <= 15 else "table"
    return mode, has_chart and mode in ("both", "chart")


def _result(text: str, results: dict, steps: list, parsed: dict | None,
            question: str, ok: bool = True) -> dict:
    """The answer the app shows: the text, and the tool results it named --
    tables and a chart drawn from the tools' own rows -- with the sources."""
    parsed = parsed or {}
    data_ids = [k for k, r in results.items() if r.get("ok") and r.get("table")]
    show = [str(x) for x in _as_list(parsed.get("show")) if str(x) in results]
    if not show and data_ids and parsed.get("action", "final") == "final":
        show = [data_ids[-1]]
    # what was looked up for the question itself is always shown
    routed = [k for k in data_ids if results[k].get("routed")]
    if parsed.get("action", "final") == "final":
        show = routed + [k for k in show if k not in routed]
    tables, chart = [], None
    for k in show:
        r = results[k]
        mode, draw = present(question, r)
        if draw and chart is None:
            chart = r["chart"]
        fold = mode == "chart" and draw
        if r.get("table"):
            tables.append({**r["table"], "collapsed": fold})
        if k == show[-1]:
            tables += [{**t, "collapsed": fold} for t in (r.get("extra_tables") or [])[:2]]
    if chart is None and _WANT_CHART.search(question or ""):
        for k in reversed(list(results)):
            if results[k].get("chart"):
                chart = results[k]["chart"]
                break
    # documents: the sections an explanation rests on, whole, with a link
    docs, seen = [], set()
    for r in results.values():
        for d in r.get("docs") or []:
            if d["id"] not in seen:
                seen.add(d["id"])
                docs.append(d)
    cites_all = {c["id"]: c for r in results.values() for c in (r.get("cites") or [])}
    if not _WANT_CODE.search(question or ""):
        # the reader checks a document, not the engine's code, unless asked
        cites_all = {i: c for i, c in cites_all.items() if c.get("kind") != "code"} or (
            {} if docs else cites_all)
    cites = [cites_all[c] for c in map(str, _as_list(parsed.get("cite"))) if c in cites_all]
    if not cites and cites_all:
        # it searched but did not say which passage: show what it read
        cites = list(cites_all.values())[:4]
    ask = None
    if parsed.get("action") == "ask":
        ask = {"question": parsed.get("question") or text,
               "options": [str(o) for o in _as_list(parsed.get("options"))][:6]}
    followups = [str(f) for f in _as_list(parsed.get("followups"))][:3]
    # every source can be opened: citations and regulatory references in the
    # text become links, and the sources are listed with theirs
    from .links import linkify, sources
    from .regulatory import REG_DIR, folder_files
    try:
        files = [p.relative_to(REG_DIR).as_posix() for p in folder_files()]
    except Exception:
        files = []
    every_cite = {c["id"]: c for r in results.values() for c in (r.get("cites") or [])}
    text = linkify(text, every_cite, files)
    if ask:
        ask["question"] = linkify(ask["question"], every_cite, files)
    named = " ".join([text] + [str(r.get("summary") or "") for r in results.values()
                               if r.get("tool") == "benchmark"])
    srcs = sources(cites, named, files)
    # which run(s) the figures come from, oldest first
    used = sorted({rid for r in results.values() if r.get("ok")
                   for rid in (r.get("runs_used") or [])})
    try:
        runs = [run_label(rid) for rid in used]
    except Exception:
        runs = [{"run_id": rid} for rid in used]
    return {"ok": ok, "text": text, "tables": tables, "chart": chart, "cites": cites,
            "docs": docs, "sources": srcs, "ask": ask, "followups": followups, "steps": steps,
            "runs": runs}


def answer(question: str, history: list[dict] | None = None,
           run_id: str | None = None,
           cfg: AssistantConfig | None = None) -> dict:
    """One question, answered (or a clarifying question back).

    Returns ``{ok, text, tables, chart, cites, ask, followups, steps}``.
    ``steps`` is the lookup trail -- which tool, which arguments, whether it
    worked -- shown under the answer, because a figure nobody can trace is
    one nobody should rely on.
    """
    cfg = cfg or load_config()
    reason = cfg.unavailable_reason()
    if reason:
        return _result(reason, {}, [], None, question, ok=False)

    history = list(history or [])
    if len(history) > cfg.max_history_turns * 2:
        history = history[-cfg.max_history_turns * 2:]

    seed = seed_context(run_id, max_chars=cfg.max_context_chars // 3)
    convo = ([{"role": "system", "content": _system_prompt(seed, run_id)}]
             + history + [{"role": "user", "content": question}])

    results: dict[str, dict] = {}
    steps: list[dict] = []
    seen_calls: dict[str, str] = {}
    calls = repairs = 0

    def ask_model() -> str | None:
        try:
            return chat(convo, cfg)
        except AssistantError as exc:
            raise _Stop(str(exc))

    checked = {"repaired": False, "nudged": False}

    def facts() -> Facts:
        texts = [_system_prompt(seed, run_id).split("EXAMPLES")[0], seed, question]
        rows: list[dict] = []
        for r in results.values():
            texts.append(r.get("summary") or "")
            for t in [r.get("table")] + list(r.get("extra_tables") or []):
                if t:
                    rows += [dict(zip(t.get("columns") or [], row)) if isinstance(row, list) else row
                             for row in (t.get("rows") or [])]
                    texts.append(" ".join(map(str, t.get("columns") or [])))
                    texts += [" ".join(map(str, row if isinstance(row, list) else row.values()))
                              for row in (t.get("rows") or [])]
            if r.get("chart"):
                rows += list(r["chart"].get("rows") or [])
        return Facts(texts, rows)

    def finish(text: str, parsed: dict, raw: str) -> dict | None:
        """The answer, checked: no table typed by the model, and no figure or
        customer that a lookup did not give. One chance to correct itself;
        then whatever is unsupported is cut out. None = asked to correct."""
        text, typed_table = strip_tables(text)
        # no lookup for a question about the run's figures: make one, never
        # send the user off to "use a tool"
        if not results and looks_like_data(question) and not checked["nudged"] \
                and parsed.get("action") != "ask":
            checked["nudged"] = True
            convo.extend([{"role": "assistant", "content": raw},
                          {"role": "user", "content":
                           "You have not looked anything up. The tools are yours, not the user's: call "
                           "the tool that answers this question now (JSON action \"tool\")."}])
            return None
        f = facts()
        opts = [str(o) for o in _as_list(parsed.get("options"))]
        bad = unsupported(text, f) + [b for o in opts for b in unsupported(o, f)]
        bad += tool_talk(text)
        if any(r.get("ok") and r.get("table") for r in results.values()):
            bad += denies(text)
        if bad and not checked["repaired"]:
            checked["repaired"] = True
            convo.extend([{"role": "assistant", "content": raw},
                          {"role": "user", "content":
                           "CHECK FAILED. These figures or customers are in no OBSERVATION or CONTEXT: "
                           + "; ".join(bad[:12]) + ". Do not invent or estimate. If you need data, call a "
                           "tool; otherwise answer again using only figures exactly as the observations "
                           "show them, and refer to the table in \"show\" instead of retyping it."}])
            return None
        removed = len(bad)
        if bad:
            text = remove(text, bad)
            if parsed.get("action") == "ask":
                parsed["options"] = [o for o in opts if not unsupported(o, f)]
        if parsed.get("action") == "ask":
            parsed["question"] = text
        if not text.strip():
            have = [r["table"] for r in results.values() if r.get("ok") and r.get("table")]
            docs = [d for r in results.values() for d in (r.get("docs") or [])]
            text = ("The documents explain it in the sections below: "
                    + "; ".join(f"**{d['heading']}**" for d in docs) + "." if docs and not have else
                    f"Here is what the lookup returned: **{have[-1].get('title') or 'the table below'}**."
                    if have else
                    "I could not find that in the run data. Try asking it another way, "
                    "or open the page that shows it.")
        # a comparison with Basel always says what Basel values are
        if any(r.get("tool") == "benchmark" for r in results.values()) and re.search(r"\bbasel\b", text, re.I) \
                and not re.search(r"capital (?:rule|requirement)", text, re.I):
            text += ("\n\n*Basel values are capital rules, used here as a reference point; IFRS 9 asks for "
                     "an unbiased estimate and does not prescribe haircuts or LGDs.*")
        out = _result(text, results, steps, parsed, question)
        out["check"] = {"removed": removed, "typed_table": typed_table}
        return out

    def lookup(name: str, args: dict, raw: str) -> str:
        nonlocal calls
        calls += 1
        tid = f"t{calls}"
        seen_calls[json.dumps([name, args], sort_keys=True, default=str)] = tid
        res = execute(name, args, run_id)
        res["tool"] = name
        results[tid] = res
        steps.append({"id": tid, "tool": name, "args": args, "ok": bool(res.get("ok"))})
        convo.extend([{"role": "assistant", "content": raw},
                      {"role": "user", "content": f"OBSERVATION {tid} ({name})"
                                                  f"{'' if res.get('ok') else ' FAILED -- state no figures from it'}:\n"
                                                  f"{_trim(res.get('summary', '(no result)'), 5000)}"}])
        return tid

    # the lookups the question plainly needs, before the model is asked
    try:
        portfolios = _portfolios(run_id)
        for name, args in route(question, history, portfolios)[:2]:
            tid = lookup(name, args, json.dumps({"action": "tool", "tool": name, "args": args}))
            results[tid]["routed"] = True
        tools_run = {r.get("tool") for r in results.values()}
        if tools_run & {"benchmark", "regulation"}:
            cfg = dataclasses.replace(cfg, max_tokens=max(cfg.max_tokens, 2000),
                                      timeout_seconds=max(cfg.timeout_seconds, 120))
            convo.append({"role": "user", "content":
                          "The lookups above hold QDB's settings beside the regulations. Reply with action "
                          "\"final\" as rule 5a says: for each item asked about, QDB's value, the "
                          "regulator's value with its paragraph, and whether QDB is higher, lower or the same; "
                          "list the benchmark lookup in \"show\" and cite the passages you use."})
        elif "explain" in tools_run and tools_run - {"explain"}:
            cfg = dataclasses.replace(cfg, max_tokens=max(cfg.max_tokens, 1500),
                                      timeout_seconds=max(cfg.timeout_seconds, 120))
            convo.append({"role": "user", "content":
                          "The lookups above hold how this portfolio is treated (document sections) and its "
                          "figures. Reply with action \"final\": first how it is treated -- rating, staging, "
                          "EAD, LGD and anything special, in a few bullets from the sections -- then what its "
                          "figures show, with the key figure; list the data lookup in \"show\" and cite "
                          "the sections."})
        elif any(r.get("tool") == "explain" for r in results.values()):
            # a methodology answer is longer than a figure: room for the steps
            cfg = dataclasses.replace(cfg, max_tokens=max(cfg.max_tokens, 2000),
                                      timeout_seconds=max(cfg.timeout_seconds, 120))
            convo.append({"role": "user", "content":
                          "The sections above answer this question; the app shows them in full, with their "
                          "formulas and a link each, under your reply. Reply with action \"final\" as rule 4 "
                          "says: in plain words the answer, then each version's steps in order with the input "
                          "each uses and what it gives -- no formulas -- with the section id in square "
                          "brackets where you use it."})
        elif results:
            convo.append({"role": "user", "content":
                          "The lookup above answers this question. Reply with action \"final\": the answer "
                          "in one or two sentences with the key figure, then up to three bullets on what "
                          "drives it; list the lookup in \"show\" and do not retype its rows."})
    except Exception:
        pass

    try:
        while True:
            raw = ask_model()
            parsed = extract_json(raw)
            if parsed is None:
                # Prose: often a perfectly good answer that skipped the format.
                if steps or repairs or len(raw or "") > 0 and "{" not in raw:
                    done = finish(raw or "The model returned nothing.", {"action": "final"}, raw or "")
                    if done is None:
                        continue
                    return done
                repairs += 1
                convo += [{"role": "assistant", "content": raw},
                          {"role": "user", "content": "Reply with one JSON object as in the protocol."}]
                continue

            action = parsed.get("action") or ("final" if "answer" in parsed else
                                              "tool" if "tool" in parsed else
                                              "ask" if "question" in parsed else "")
            parsed["action"] = action
            if action in ("final", "ask") or action != "tool":
                if action == "final":
                    text = parsed.get("answer") or "(empty answer)"
                elif action == "ask":
                    text = parsed.get("question") or "Could you say a bit more?"
                else:
                    text, parsed = raw, {"action": "final"}
                done = finish(text, parsed, raw)
                if done is None:
                    continue
                return done

            name = str(parsed.get("tool") or "")
            args = parsed.get("args") if isinstance(parsed.get("args"), dict) else {}
            key = json.dumps([name, args], sort_keys=True, default=str)
            if key in seen_calls:
                convo += [{"role": "assistant", "content": raw},
                          {"role": "user", "content": f"You already have that result as {seen_calls[key]}. "
                                                      'Answer now with action "final".'}]
                calls += 1
                if calls > cfg.max_tool_calls:
                    break
                continue
            if calls >= cfg.max_tool_calls:
                break
            lookup(name, args, raw)
            # keep the prompt small: older observations shrink once read
            obs = [i for i, m in enumerate(convo) if m["role"] == "user"
                   and m["content"].startswith("OBSERVATION")]
            for i in obs[:-3]:
                convo[i] = {"role": "user", "content": _trim(convo[i]["content"], 1200)}

        convo.append({"role": "user", "content": 'Lookup limit reached. Answer now with action "final" '
                                                 "from what you have."})
        raw = ask_model()
        parsed = extract_json(raw) or {"action": "final", "answer": raw}
        parsed.setdefault("action", "final")
        checked["repaired"] = True            # no lookups left to correct with
        return finish(parsed.get("answer") or raw, parsed, raw)
    except _Stop as stop:
        return _result(str(stop), results, steps, None, question, ok=False)


class _Stop(Exception):
    pass
