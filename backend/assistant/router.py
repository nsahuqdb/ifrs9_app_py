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
        return [("movement", {"run_a": "previous", **({"run_b": run} if run else {}), "level": level})]
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
    if SCEN.search(q) and not HOW.search(q):
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
        return [("search_docs", {"query": q, "scope": "all"})]
    return []


def looks_like_data(question: str) -> bool:
    """A question whose answer is a figure from a run."""
    return bool(DATA.search(question)) and not (HOW.search(question)
                                                and not re.search(r"how (much|many)", question, re.I))
