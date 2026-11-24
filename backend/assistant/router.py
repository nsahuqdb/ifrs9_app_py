"""The lookups a question plainly needs, made before the model is asked.

A small chat model often answers a data question from nowhere, or tells the
user to "use the top tool". So the usual questions -- a list of customers, a
split, the movement, the failed checks, the macro model, PD curves, how
something works -- are recognised here by their words and looked up first.
The model then only has to write a sentence about a result it already holds,
and the table under the reply comes from that lookup whatever it writes.

A question this does not recognise is left to the model, which can still
call any lookup itself.
"""
from __future__ import annotations

import re

_W = lambda *ws: re.compile(r"\b(?:" + "|".join(ws) + r")\b", re.I)

CUSTOMERS = _W(r"cust\w*", r"client\w*", "counterpart(?:y|ies)", "obligors?", "borrowers?", "names?")
CONTRACTS = _W("contracts?", "facilit(?:y|ies)", "accounts?", "loans?")
LIST = _W("list", "top", "largest", "biggest", "highest", "main", "which", "who", "show", "where")
SPLIT = _W("split", "breakdown", "break down", "distribution", "by")
MOVE = _W("mov(?:e|ed|ement)", "bridge", "waterfall", "why did", "change since", "changed since",
          "between the (?:two )?runs", "compared? to (?:the )?previous")
VALID = _W("validation", "checks?", "failed", "failures?")
MEV = _W("mevs?", "coefficients?", "macro model", "macro variables?", "intercept", "regression")
PDC = _W("pd curves?", "term structure", "pd term")
SCEN = _W("scenarios?", "scenario weights?", "weights")
HOW = re.compile(r"^\s*(how|why|what is|what are|what does|explain|where (?:is|do|can) .* (?:page|set|done))\b", re.I)
DATA = _W("ecl", "provision", "exposure", "stage", "portfolio", "customers?", "coverage", "rating",
          "run", "movement", "top", "list", "total", "amount", "lgd", "pd", "overlay")

FIGURE = re.compile(r"\b(total|overall|how much|how many|amount|sum)\b|\bwhat (?:is|are|was|were) (?:the |our )?"
                    r"(?:total |overall |booked )?(?:ecl|provision|exposure|coverage|overlay)\b", re.I)
METHOD = re.compile(r"calculat|method|defin|formula|\bmean|\bwork|comput|determin|derive|treat", re.I)

DIMS = {"portfolio": _W("portfolios?", "segments?"), "stage": _W("stages?"),
        "rating": _W("ratings?", "grades?"), "account_type": _W("account types?", "products?"),
        "maturity_band": _W("maturity", "remaining term"), "dpd_band": _W("dpd", "days past due")}


def _run_ref(q: str) -> str | None:
    m = re.search(r"\brun[_ ]?0*(\d+)\b", q, re.I)
    if m:
        return f"run_{int(m.group(1)):05d}"
    return None


def _filters(q: str, portfolios: list[str]) -> dict:
    f: dict = {}
    m = re.search(r"\bstage\s*([123])\b|\bs([123])\b", q, re.I)
    if m:
        f["stage"] = int(m.group(1) or m.group(2))
    ql = q.lower()
    for p in sorted(portfolios, key=len, reverse=True):
        if p and p.lower() in ql:
            f["portfolio"] = p
            break
    return f


def _n(q: str, default: int = 10) -> int:
    m = re.search(r"\btop\s*(\d{1,3})\b|\b(\d{1,3})\s*(?:largest|biggest|highest|top|customers|contracts)\b",
                  q, re.I)
    return int(m.group(1) or m.group(2)) if m else default


CODE = re.compile(r"\b(code|function|python|source|implementation|implemented|script|module|class)\b", re.I)
EXPLAIN = re.compile(r"^\s*(how (?:is|are|does|do|was|were|can|should)|what (?:is|are|does) (?:a |an |the )?"
                     r"(?!total|overall|booked|our|ecl of|provision of)|explain|define|definition|meaning|"
                     r"describe|tell me about)\b|\b(methodolog\w*|formula\w*|calculat\w*|approach|logic|"
                     r"defin\w*|treat\w*|assumption\w*)\b", re.I)
STAGE_MOVE = re.compile(r"\b(mov\w*|migrat\w*|went|gone|shift\w*|transition\w*|downgrad\w*|upgrad\w*|"
                        r"deteriorat\w*|improv\w*|cured?|fell|slipped|jumped)\b.*\bstages?\b|"
                        r"\bstages?\s*[123]\s*(?:to|→|->|-)\s*(?:stage\s*)?[123]\b|\bfrom stage\b|"
                        r"\bstages?\b.*\b(mov\w*|migrat\w*|downgrad\w*|upgrad\w*|transition\w*)\b", re.I)
RATING_MOVE = re.compile(r"\b(rating|grade)s?\b.*\b(migrat\w*|downgrad\w*|upgrad\w*|mov\w*|chang\w*)\b|"
                         r"\b(downgrad\w*|upgrad\w*)\b(?!.*stage)", re.I)
DIFF = _W("difference", "differences", "differ", "compare", "comparison", "versus", "vs", "against")
WHY_STAGE = re.compile(r"\bwhy\b.*\b(?:in|at|into|to|is)\s+stage\s*[123]\b|\bwhy\b.*\bstage\s*[123]\b|"
                       r"\b(?:stage|staging) reasons?\b|\breason\b.*\bstage\b", re.I)
RESULTS = _W("results?", "summary", "summarise", "summarize", "overview", "headline", "key figures",
             "how did the run", "where do we stand")
TRIGGERS = _W("triggers?", "drivers?", "why are", "reasons?")


REGULATOR = re.compile(r"\b(basel|bcbs|cre\s?\d{2}|qcb|qatar central bank|central bank|regulat\w*|regulator\w*|"
                       r"supervis\w*|circular|guideline\w*|eba|ecb|bank of england|boe|pra|fed|federal reserve|"
                       r"ccar|dfast|finma|icaap|compliant|compliance|benchmark\w*|"
                       r"ifrs\s?9\s+(?:standard|paragraph|requir\w*|says?|presum\w*)|"
                       r"(?:according to|under|per|vs\.?|versus|against|compared? (?:to|with))\s+ifrs\s?9)\b", re.I)
REG_DOCS = re.compile(r"\b(which|what|list)\b.*\b(regulat\w*|circulars?|documents?|texts?)\b.*"
                      r"\b(have|available|folder|loaded|read)\b", re.I)


def _stage_pair(q: str) -> tuple[int | None, int | None]:
    m = re.search(r"\bstages?\s*([123])\s*(?:to|→|->|-|into)\s*(?:stage\s*)?([123])\b", q, re.I)
    if m:
        return int(m.group(1)), int(m.group(2))
    fr = re.search(r"\bfrom stage\s*([123])\b", q, re.I)
    to = re.search(r"\b(?:to|into|in) stage\s*([123])\b", q, re.I)
    return (int(fr.group(1)) if fr else None), (int(to.group(1)) if to else None)


def _who(q: str) -> str | None:
    """The customer a "why is X in Stage 2" question names: an id, or the
    words between the verb and "in/at stage"."""
    m = re.search(r"\b(\d{4,})\b", q)
    if m:
        return m.group(1)
    m = re.search(r"\bwhy\s+(?:is|was|are|were|did|does|has)\s+(?:customer\s+|client\s+)?(.+?)\s+"
                  r"(?:in|at|into|moved|move|go|went|classified|staged|placed|put)\b", q, re.I)
    if m:
        who = m.group(1).strip(" '\"")
        if not re.fullmatch(r"(?:the |this |that |these |those |our |all |many |so many )?"
                            r"(?:customers?|clients?|contracts?|facilit\w+|it|they|them|he|she|ecl|exposure)",
                            who, re.I):
            return who
    return None


def plan(question: str, history: list[dict] | None = None,
         portfolios: list[str] | None = None) -> list[tuple[str, dict]]:
    """The lookups to make first: [(tool, args)], or [] to leave it to the
    model. A short follow-up ("where is the stage 2 list?", "and stage 3?")
    borrows what it does not say from the previous question."""
    q = question.strip()
    prev = ""
    for t in reversed(history or []):
        if t.get("role") == "user":
            prev = str(t.get("content") or "")
            break
    portfolios = portfolios or []
    run = _run_ref(q)
    base = {"run_id": run} if run else {}
    f = _filters(q, portfolios)
    measure = ("coverage" if re.search(r"\bcoverage\b", q, re.I) else
               "lgd" if re.search(r"\blgd\b", q, re.I) else
               "pd" if re.search(r"\bpd\b", q, re.I) else
               "exposure" if re.search(r"\b(exposure|balance|outstanding)\b", q, re.I) else "ecl")
    if re.search(r"\bhow many\b", q, re.I):
        measure = "customers" if CUSTOMERS.search(q) else "contracts"

    # a follow-up that names a filter but not what to do: the previous ask, re-filtered
    short = len(q.split()) <= 8
    if short and prev and not (CUSTOMERS.search(q) or CONTRACTS.search(q) or SPLIT.search(q)
                               or MOVE.search(q)) and (f or LIST.search(q)):
        inherited = plan(prev, None, portfolios)
        if inherited and inherited[0][0] in ("top", "breakdown"):
            tool, args = inherited[0]
            args = dict(args)
            if f:
                args["filters"] = {**(args.get("filters") or {}), **f}
            if run:
                args["run_id"] = run
            if re.search(r"\blist\b", q, re.I) and tool == "top" and not re.search(r"\btop\s*\d", q, re.I):
                args["n"] = max(int(args.get("n") or 10), 10)
            return [(tool, args)]

    two = bool(re.search(r"\b(previous|last quarter|prior|two runs|both runs|since|between)\b", q, re.I)
               or len(re.findall(r"\brun[_ ]?\d+", q, re.I)) >= 2)
    runs = re.findall(r"\brun[_ ]?0*(\d+)\b", q, re.I)
    pair = ({"run_a": f"run_{int(runs[0]):05d}", "run_b": f"run_{int(runs[1]):05d}"} if len(runs) >= 2
            else {"run_b": run} if run else {})

    # regulation: what the rules say, and QDB beside them
    if REG_DOCS.search(q):
        return [("reg_documents", {})]
    if REGULATOR.search(q):
        from .regulatory import topic_of
        topics = topic_of(q)
        plan_ = []
        if topics:
            plan_.append(("benchmark", {**base, "topic": topics[0]}))
        plan_.append(("regulation", {"query": q}))
        return plan_
    # one portfolio: how it is treated, and where it stands
    if f.get("portfolio") and re.search(r"\b(about|going on|tell me|profile|overview|happening|treat\w*|"
                                        r"methodolog\w*|how (?:is|are|does))\b", q, re.I) \
            and not (CUSTOMERS.search(q) or MOVE.search(q) or FIGURE.search(q)):
        p = f["portfolio"]
        steps = [("explain", {"query": f"{p} portfolio"})]
        if not re.search(r"\b(treat\w*|methodolog\w*|how (?:is|are|does))\b", q, re.I):
            steps.append(("compare", {"run_a": "previous", **({"run_b": run} if run else {}),
                                      "by": ["stage"], "measure": "ecl", "filters": {"portfolio": p}}))
        return steps
    # the code, only when asked for it
    if CODE.search(q) and re.search(r"\b(where|which|show|how)\b", q, re.I):
        return [("search_docs", {"query": q, "scope": "code"})]
    if re.search(r"\bmigration matrix\b|\bstage migration\b|\bmatrix\b.*\bstage", q, re.I):
        args = {"run_a": pair.get("run_a", "previous"), **({"run_b": pair["run_b"]} if pair.get("run_b") else {})}
        return [("migration", {**args, "kind": "stage"}), ("stage_moves", args)]
    if re.search(r"\bcur(?:e|ed|es|ing)\b", q, re.I) and (CUSTOMERS.search(q) or LIST.search(q)):
        args = {"run_a": pair.get("run_a", "previous"), **({"run_b": pair["run_b"]} if pair.get("run_b") else {})}
        return [("stage_moves", {**args, "direction": "better"})]
    # who moved between stages, and why
    if STAGE_MOVE.search(q) and not re.search(r"^\s*how (?:is|are|does)\b", q, re.I):
        fr, to = _stage_pair(q)
        args = {"run_a": pair.get("run_a", "previous"), **({"run_b": pair["run_b"]} if pair.get("run_b") else {})}
        if fr:
            args["from_stage"] = fr
        if to:
            args["to_stage"] = to
        if not (fr or to):
            if re.search(r"downgrad|deteriorat|worse|fell|slipped|jumped", q, re.I):
                args["direction"] = "worse"
            elif re.search(r"upgrad|improv|cure|better", q, re.I):
                args["direction"] = "better"
        return [("stage_moves", args)]
    if RATING_MOVE.search(q):
        return [("migration", {"run_a": pair.get("run_a", "previous"),
                               **({"run_b": pair["run_b"]} if pair.get("run_b") else {}), "kind": "rating"})]
    # why a customer is in its stage; why customers are in a stage
    if WHY_STAGE.search(q):
        who = _who(q)
        if who:
            return [("stage_reason", {**base, "query": who})]
        return [("staging", base)]
    if re.search(r"\bstag\w*\b", q, re.I) and TRIGGERS.search(q) and not EXPLAIN.search(q):
        return [("staging", base)]
    # what differs between two runs: the numbers side by side, and why
    if DIFF.search(q) and (two or len(runs) >= 2 or re.search(r"\bruns?\b|quarter", q, re.I)):
        dims = [d for d, rx in DIMS.items() if rx.search(q)] or ["portfolio"]
        args = {"run_a": pair.get("run_a", "previous"), **({"run_b": pair["run_b"]} if pair.get("run_b") else {})}
        return [("compare", {**args, "by": dims[:1], "measure": measure if measure != "pd" else "ecl",
                             **({"filters": f} if f else {})}),
                ("movement", {**args, "level": "book"})]
    # how something is calculated, decided or done: the documents
    a_value = (MEV.search(q) or PDC.search(q) or (VALID.search(q) and re.search(r"validation|check", q, re.I))
               or (SCEN.search(q) and re.search(r"\bweights?\b|\bscenario\b", q, re.I))) \
        and not re.search(r"^\s*(how|explain|why|describe)\b|methodolog|formula|calculat", q, re.I)
    if EXPLAIN.search(q) and not FIGURE.search(q) and not a_value \
            and not re.search(r"\bwhy did\b|\bwhich\b|\bwho\b", q, re.I):
        if not (MOVE.search(q) and re.search(r"\bwhy\b", q, re.I)):
            return [("explain", {"query": q})]
    if RESULTS.search(q) and not EXPLAIN.search(q):
        return [("overview", base)]
    if VALID.search(q) and re.search(r"validation|check", q, re.I):
        return [("validation", {**base, "only_failures": bool(re.search(r"fail", q, re.I))})]
    if MEV.search(q):
        return [("model", base)]
    if PDC.search(q):
        ratings = re.findall(r"\b(?:QDB|AAA|AA|A|BBB|BB|B|CCC)\s*[0-9]*[+-]?", q)
        return [("pd_curve", {**base, **({"ratings": [r.strip() for r in ratings]} if ratings else {})})]
    if MOVE.search(q):
        level = next((d for d in ("portfolio", "stage", "rating", "account_type") if DIMS[d].search(q)),
                     "customer" if CUSTOMERS.search(q) else "book")
        args = {"run_a": pair.get("run_a", "previous"), **({"run_b": pair["run_b"]} if pair.get("run_b") else {})}
        member = re.search(r"\b(\d{4,})\b", q)
        if level == "customer" and member:
            args["member"] = member.group(1)
        return [("movement", {**args, "level": level})]
    dims = [d for d, rx in DIMS.items() if rx.search(q)]
    if re.search(r"\bhow many\b", q, re.I):
        return [("breakdown", {**base, "by": [d for d in dims if not (d == "stage" and f.get("stage"))][:2],
                               "measure": measure, **({"filters": f} if f else {})})]
    other_dims = [d for d, rx in DIMS.items() if rx.search(q) and d != "stage"]
    a_list = bool(re.search(r"\blist\b", q, re.I)) and f and not other_dims
    if (CUSTOMERS.search(q) or CONTRACTS.search(q) or a_list) and (LIST.search(q) or f):
        by = "contract" if CONTRACTS.search(q) and not CUSTOMERS.search(q) else "customer"
        tm = measure if measure in ("ecl", "exposure", "coverage") else "ecl"
        return [("top", {**base, "by": by, "measure": tm, "n": _n(q), **({"filters": f} if f else {})})]
    if SCEN.search(q) and not re.search(r"^\s*(how|explain|why|describe)\b", q, re.I):
        return [("scenarios", base)]
    dims = [d for d, rx in DIMS.items() if rx.search(q)]
    if dims and (SPLIT.search(q) or LIST.search(q)) and not HOW.search(q):
        by = dims[:2] if len(dims) > 1 else dims
        if f.get("stage") and "stage" in by and len(by) > 1:
            by = [d for d in by if d != "stage"]
        return [("breakdown", {**base, "by": by, "measure": measure, **({"filters": f} if f else {})})]
    if FIGURE.search(q) and not METHOD.search(q):
        if f or dims:
            return [("breakdown", {**base, "by": [d for d in dims if not (d == "stage" and f.get("stage"))][:2],
                                   "measure": measure, **({"filters": f} if f else {})})]
        return [("overview", base)]
    if HOW.search(q) and not re.search(r"\b(how much|how many)\b", q, re.I):
        return [("explain", {"query": q})]
    return []


def looks_like_data(question: str) -> bool:
    """A question whose answer is a figure from a run."""
    return bool(DATA.search(question)) and not (HOW.search(question)
                                                and not re.search(r"how (much|many)", question, re.I))
