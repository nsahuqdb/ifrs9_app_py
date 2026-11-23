"""Every figure in an answer must come from a lookup.

A language model writes fluent numbers whether or not it has them. This module
checks the model's text against what the lookups actually returned (and the
context it was given): each amount, percentage and customer id, and the name
written beside an id. What it cannot find is not shown. The tables under the
answer are drawn from the lookups' own rows and never pass through the model,
so the model is also stopped from retyping them in its text.
"""
from __future__ import annotations

import re

import numpy as np

# a number as written: 1,234,567 · 12.5 · -3 · 48.6% · 177.9 mln · 2.3bn
_NUM = re.compile(
    r"(?<![\w.\-/])(?P<sign>[-−–]?)(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<unit>\s*(?:%|percent\b|mln\b|million\b|mn\b|m\b|bn\b|billion\b|k\b|thousand\b))?",
    re.I)
# things that look like numbers and are not figures
_SKIP = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),                 # 2026-09-30
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"),           # 30/9/2026
    re.compile(r"\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4}\b", re.I),
    re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4}\b", re.I),
    re.compile(r"\brun[_ ]?\d+\b", re.I),                 # run_00023
    re.compile(r"\b(?:stage|qdb|q|k|t|step|section|chapter|page|v|version)\s*\d+[+-]?", re.I),
    re.compile(r"\b\d+\.\d+\.\d+\b"),                 # 0.53.0, a version
    re.compile(r"\b(?:top|first|last)\s+\d+\b", re.I),
    re.compile(r"\[k\d+\]"),
]
_SCALE = {"%": 1.0, "percent": 1.0, "mln": 1e6, "million": 1e6, "mn": 1e6, "m": 1e6,
          "bn": 1e9, "billion": 1e9, "k": 1e3, "thousand": 1e3}
# "20111 · Ahmed Trading": an id with the name the tables show beside it
_ID_NAME = re.compile(r"\b(\d{3,})\s*[·•]\s*(?=\S)")
_ROW_NAME = re.compile(r"^\s*(\d{3,})\s*[·•]\s*(.+?)\s*$")
_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$")
_RULE_LINE = re.compile(r"^\s*\|?\s*:?-{3,}")


def _value(m: re.Match) -> tuple[float, int, float, bool]:
    """(mantissa, decimals written, scale, is_percent)."""
    num = m.group("num").replace(",", "")
    dec = len(num.split(".")[1]) if "." in num else 0
    unit = (m.group("unit") or "").strip().lower()
    v = float(num) * (-1 if m.group("sign") else 1)
    return v, dec, _SCALE.get(unit, 1.0), unit in ("%", "percent")


def _blank_skips(text: str) -> str:
    for rx in _SKIP:
        text = rx.sub(lambda m: " " * len(m.group(0)), text)
    return text


def numbers_in(text: str) -> list[float]:
    """Every figure in a body of text, as plain values (the facts side)."""
    out = []
    for m in _NUM.finditer(_blank_skips(text or "")):
        v, _, scale, _ = _value(m)
        out.append(v * scale)
    return out


class Facts:
    """What the answer may state: the lookups' text and rows, the context the
    model was given, and the question itself."""

    def __init__(self, texts: list[str], rows: list[dict] | None = None):
        self.text = "\n".join(t for t in texts if t)
        self.low = self.text.lower()
        # the name each customer id carries in the lookups' rows
        self.names: dict[str, set[str]] = {}
        for r in rows or []:
            for v in r.values():
                if isinstance(v, str):
                    m = _ROW_NAME.match(v)
                    if m:
                        self.names.setdefault(m.group(1), set()).add(m.group(2).lower())
        vals = numbers_in(self.text)
        for r in rows or []:
            for v in r.values():
                if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v:
                    vals.append(float(v))
        a = np.unique(np.array([v for v in vals if np.isfinite(v)], dtype=float))
        # rates kept as fractions somewhere and written as percent elsewhere
        small = a[np.abs(a) <= 1.5] * 100
        self.base = np.unique(np.concatenate([a, small, -a]))
        # what a careful reader may work out from them: a difference, a sum,
        # a share -- among the larger figures only, which is where it happens
        big = np.unique(np.abs(a))[-300:]
        if len(big) > 1:
            x, y = np.meshgrid(big, big)
            with np.errstate(divide="ignore", invalid="ignore"):
                der = np.concatenate([(x - y).ravel(), (x + y).ravel(),
                                      (100 * x / y).ravel(), (100 * (x - y) / y).ravel()])
            der = der[np.isfinite(der)]
            self.derived = np.unique(np.concatenate([der, -der]))
        else:
            self.derived = np.array([])

    def has(self, v: float, dec: int, scale: float) -> bool:
        """Whether a figure written to ``dec`` decimals in units of ``scale``
        is one of the facts, rounded or truncated as written."""
        tol = 10.0 ** (-dec) * scale + 1e-9 * max(1.0, abs(v * scale))
        target = v * scale
        for arr in (self.base, self.derived):
            if len(arr) == 0:
                continue
            i = np.searchsorted(arr, target)
            for j in (i - 1, i, i + 1):
                if 0 <= j < len(arr) and abs(arr[j] - target) <= tol:
                    return True
        return False

    def name_after(self, cid: str, after: str) -> bool:
        """Whether the text written after "<id> · " starts with the name the
        lookups give that id."""
        a = re.sub(r"\s+", " ", after).lower().lstrip("*_ ")
        return any(a.startswith(n) for n in self.names.get(cid, ()))


def unsupported(text: str, facts: Facts) -> list[str]:
    """The figures and customer names in ``text`` that no lookup gave."""
    bad: list[str] = []
    blanked = _blank_skips(text or "")
    for m in _NUM.finditer(blanked):
        v, dec, scale, is_pct = _value(m)
        unit = bool(m.group("unit"))
        # a small whole number with no unit is a count or a label (3 customers,
        # 5 scenarios), not an amount
        if not unit and dec == 0 and abs(v) < 1000:
            continue
        if not unit and dec == 0 and 1990 <= abs(v) <= 2100:
            continue                                          # a year
        if not facts.has(v, dec, scale):
            bad.append(m.group(0).strip())
    for m in _ID_NAME.finditer(text or ""):
        cid = m.group(1)
        if not facts.name_after(cid, (text or "")[m.end():m.end() + 120]):
            bad.append(m.group(0).strip())
    out, seen = [], set()
    for b in bad:
        if b not in seen:
            seen.add(b)
            out.append(b)
    return out


def strip_tables(text: str) -> tuple[str, bool]:
    """The answer without any table the model typed (markdown, or columns
    separated by tabs): tables come from the lookups, drawn by the app."""
    lines = (text or "").splitlines()
    keep, cut = [], False
    for ln in lines:
        if _TABLE_LINE.match(ln) or _RULE_LINE.match(ln) or ln.count("\t") >= 1:
            cut = True
            continue
        keep.append(ln)
    out = "\n".join(keep)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out, cut


_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z*(\[])")


def remove(text: str, bad: list[str]) -> str:
    """The answer without every line or sentence that carries a figure no
    lookup gave."""
    if not bad:
        return text
    out_lines = []
    for ln in (text or "").splitlines():
        if not any(b in ln for b in bad):
            out_lines.append(ln)
            continue
        if re.match(r"^\s*([-*•]|\d+\.)\s", ln):
            continue                                      # a bullet: drop it whole
        kept = [s for s in _SENT.split(ln) if not any(b in s for b in bad)]
        if kept:
            out_lines.append(" ".join(kept))
    out = "\n".join(out_lines)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


_TOOL_NAMES = ("overview", "breakdown", "compare", "movement", "migration", "top", "customer",
               "staging", "scenarios", "pd_curve", "concentration", "validation", "run_info",
               "search_docs", "read_code", "config_file", "aggregate", "filter_rows")
_TOOL_TALK = re.compile(r"(\btools?[\"'`”]? page|\bnavigat\w* to the [\"'`“]?tools?|the [\"'`“]?(?:" + "|".join(_TOOL_NAMES) + r")[\"'`”]? tool|"
                        r"\w+\s+parameter|use the tool|call the tool|run the tool)\b", re.I)


def tool_talk(text: str) -> list[str]:
    """Sentences telling the user to use a lookup tool: the tools are the
    assistant's, and the app has no page for them."""
    out = []
    for ln in (text or "").splitlines():
        for s in _SENT.split(ln):
            if _TOOL_TALK.search(s):
                out.append(s.strip())
    return out


_NOT_HAVE = re.compile(r"\b(do not|don't|cannot|can't|unable to|no access)\b[^.]*\b(have|find|access|provide|see|show)\b",
                       re.I)


def denies(text: str) -> list[str]:
    """Sentences saying the data is not available, for a reply that has the
    lookup's table under it."""
    return [s.strip() for ln in (text or "").splitlines() for s in _SENT.split(ln) if _NOT_HAVE.search(s)]
