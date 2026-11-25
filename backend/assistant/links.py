"""Links in an answer: every source it names can be opened in a new tab.

* ``[k19]`` -- a passage the answer rests on -- becomes a link to it: a
  section of a Help document opens that document at the section; a page of a
  regulatory text in docs/regulatory opens that file at the page.
* A regulatory reference written in the text -- CRE22.49, B5.5.37, 5.5.11, the
  EBA Methodological Note ... -- becomes a link to the official document, or
  to the user's own copy when docs/regulatory holds it.

A file in docs/regulatory is written as ``regfile://<path>``; the front end
puts the backend's address in front (it knows where the backend is, the
backend does not know how the browser reaches it).
"""
from __future__ import annotations

import re
from urllib.parse import quote

# Official sources, as published (checked November 2026).
OFFICIAL = {
    "CRE20": ("Basel Framework CRE20", "https://www.bis.org/committees/bcbs/basel-framework/81428/chapter.pdf"),
    "CRE22": ("Basel Framework CRE22", "https://www.bis.org/committees/bcbs/basel-framework/81430/chapter.pdf"),
    "CRE32": ("Basel Framework CRE32", "https://www.bis.org/committees/bcbs/basel-framework/81431/chapter.pdf"),
    "IFRS9": ("IFRS 9 (EU-endorsed text, Regulation 2016/2067)",
              "https://www.legislation.gov.uk/eur/2016/2067/annex/adopted"),
    "D450": ("BCBS Stress testing principles (2018)", "https://www.bis.org/bcbs/publ/d450.htm"),
    "EBA": ("EBA 2025 EU-wide stress test, Methodological Note",
            "https://www.eba.europa.eu/sites/default/files/2024-11/ee01efca-947b-43ae-b17d-20f9d4314e8e/"
            "2025%20EU-wide%20stress%20test%20-%20Methodological%20Note.pdf"),
    "BOE": ("Bank of England, Key elements of the 2025 Bank Capital Stress Test",
            "https://www.bankofengland.co.uk/stress-testing/2025/key-elements-bank-capital"),
    "FED": ("Federal Reserve, 2026 stress test", "https://www.federalreserve.gov/publications/"
            "2026-june-dodd-frank-act-stress-test-introduction.htm"),
    "FINMA": ("FINMA, stress tests",
              "https://finma.ch/en/supervision/banks-and-securities-firms/supervisory-instruments/stress-tests"),
    "QCBB3": ("QCB Implementation Instructions, Basel III Framework for Conventional Banks (Pillar 1, 2014)",
              "https://www.qcb.gov.qa/Documents/BankInstructions2024/AR/0381-0464_annex001.pdf"),
    "KPMG": ("KPMG, IFRS 9 transition impact on banks in the GCC – Qatar",
             "https://assets.kpmg.com/content/dam/kpmg/qa/pdf/10/ifrs9-transition-impact-on-banks-in-the-gcc-"
             "qatar-web-version.pdf"),
}

# What, in a file's name, says it is one of these (for the user's own copy).
LOCAL_NAME = {
    "CRE20": r"cre\s*-?_?20", "CRE22": r"cre\s*-?_?22", "CRE32": r"cre\s*-?_?32",
    "IFRS9": r"ifrs\s*-?_?9", "EBA": r"\beba\b|methodological", "QCB": r"9\s*[-_/ ]\s*2017|circular\s*9", "QCBB3": r"0381|basel\s*iii.*conventional|pillar\s*1",
}

# reference in text -> source key
PATTERNS = [
    (re.compile(r"\bCRE\s?(20|22|32)(?:\.\d+(?:\s?[–-]\s?(?:\d+\.)?\d+)?)?"), lambda m: f"CRE{m.group(1)}"),
    (re.compile(r"(?<![\w.])(?:B5\.5\.\d+(?:\s?[–-]\s?(?:B5\.5\.)?\d+)?|5\.5\.\d+(?:\s?[–-]\s?(?:5\.5\.)?\d+)?|5\.4\.4)(?![\w.]*\d)"),
     lambda m: "IFRS9"),
    (re.compile(r"\bMethodological Note\b"), lambda m: "EBA"),
    (re.compile(r"\bBank Capital Stress Test\b"), lambda m: "BOE"),
    (re.compile(r"\b(?:Supervisory Stress Test|Stress Test Results)\b"), lambda m: "FED"),
    (re.compile(r"\bd450\b|\bStress testing principles\b"), lambda m: "D450"),
    (re.compile(r"\bQCB Basel III Pillar 1 instructions\b"), lambda m: "QCBB3"),
    (re.compile(r"\bKPMG\b"), lambda m: "KPMG"),
    (re.compile(r"\b(?:QCB\s+)?Circular\s+(?:No\.?\s*)?9/2017\b"), lambda m: "QCB"),
]

_MDLINK = re.compile(r"\[[^\]]*\]\([^)]*\)")


def page_url(link: dict | None) -> str | None:
    """The address of a Help document section: /help_ecl?ch=..&sec=.."""
    if not link or not link.get("page"):
        return None
    stem = link["page"].rsplit("/", 1)[-1].removesuffix(".py")
    q = "&".join(f"{k}={quote(str(v))}" for k, v in (("ch", link.get("ch")), ("sec", link.get("sec"))) if v)
    return f"/{stem}" + (f"?{q}" if q else "")


def local_copy(key: str, files: list[str]) -> str | None:
    """The user's own copy of a source in docs/regulatory, if there is one."""
    rx = LOCAL_NAME.get(key)
    if not rx:
        return None
    for f in files:
        if re.search(rx, f.rsplit("/", 1)[-1], re.I):
            return f
    return None


def source_url(key: str, files: list[str]) -> tuple[str, str] | None:
    """(label, url) for a source key: the user's copy first, else the official one."""
    own = local_copy(key, files)
    if own:
        return (own.rsplit("/", 1)[-1], "regfile://" + quote(own))
    return OFFICIAL.get(key)


def cite_url(cite: dict) -> tuple[str, str] | None:
    """(short label, url) for a passage the answer cites."""
    if cite.get("kind") == "reg":
        where = str(cite.get("where") or "")
        rel = where.removeprefix("docs/regulatory/")
        page = re.search(r"(\d+)", str(cite.get("section") or ""))
        return (f"{rel.rsplit('/', 1)[-1]}, {cite.get('section', '')}",
                "regfile://" + quote(rel) + (f"#page={page.group(1)}" if page else ""))
    url = page_url(cite.get("link"))
    if url:
        lab = cite["link"].get("label") or cite.get("label") or "document"
        return lab, url
    return None


_DOC_SHORT = {"ecl_methodology": "", "user_manual": "User manual ", "stress_testing_methodology": "Stress methodology ",
              "regulatory_reference": "Regulatory reference "}


def short_label(cite: dict, label: str) -> str:
    """A citation as it sits in a sentence: "§7.4" for the ECL methodology,
    "User manual §9.5", or the file and page of a regulatory text."""
    if cite.get("kind") == "reg":
        return label
    head = (cite.get("link") or {}).get("sec") or label.split(" › ")[-1]
    num = re.match(r"(\d+(?:\.\d+)?)", str(head))
    pre = _DOC_SHORT.get(str(cite.get("source")), "")
    return f"{pre}§{num.group(1)}" if num else f"{pre}{head}"


def linkify(text: str, cites: dict[str, dict] | None = None, files: list[str] | None = None) -> str:
    """The answer with its citations and regulatory references as links."""
    if not text:
        return text
    cites = cites or {}
    files = files or []

    def cite_sub(m: re.Match) -> str:
        ids = [x.strip() for x in m.group(1).split(",")]
        parts = []
        for i in ids:
            c = cites.get(i)
            got = cite_url(c) if c else None
            if got:
                lab, url = got
                parts.append(f"[{short_label(c, lab)} ↗]({url})")
            else:
                parts.append(f"[{i}]")
        return "(" + "; ".join(parts) + ")" if any("↗" in p for p in parts) else m.group(0)

    text = re.sub(r"\[(k\d+(?:\s*,\s*k\d+)*)\]", cite_sub, text)

    # "[CRE22.49; CRE32.11]": a model's brackets around references would read
    # as Markdown link text; they become parentheses
    text = re.sub(r"\[([^\[\]]*?(?:CRE\s?\d{2}|B5\.5\.\d|5\.5\.\d|5\.4\.4)[^\[\]]*?)\](?!\()",
                  r"(\1)", text)
    # every regulatory reference becomes a link, never inside a link already made
    for rx, key_of in PATTERNS:
        out, pos = [], 0
        protected = [(a.start(), a.end()) for a in _MDLINK.finditer(text)]
        for m in rx.finditer(text):
            if any(a <= m.start() < b for a, b in protected):
                continue
            src = source_url(key_of(m), files)
            if not src:
                continue
            out.append(text[pos:m.start()])
            out.append(f"[{m.group(0)}]({src[1]})")
            pos = m.end()
        if out:
            out.append(text[pos:])
            text = "".join(out)
    return text


def first_url(ref: str, files: list[str] | None = None) -> str | None:
    """The address of the first source a reference cell names (for a table)."""
    for rx, key_of in PATTERNS:
        m = rx.search(ref or "")
        if m:
            src = source_url(key_of(m), files or [])
            if src:
                return src[1]
    return None


def sources(cites: list[dict], text: str, files: list[str] | None = None) -> list[dict]:
    """Every source behind an answer as {label, url}: the passages it cites
    and the regulatory documents its text or tables name."""
    files = files or []
    out, seen = [], set()
    for c in cites:
        got = cite_url(c)
        if got and got[1] not in seen:
            seen.add(got[1])
            out.append({"label": got[0], "url": got[1]})
    for rx, key_of in PATTERNS:
        for m in rx.finditer(text or ""):
            src = source_url(key_of(m), files)
            if src and src[1] not in seen:
                seen.add(src[1])
                out.append({"label": src[0], "url": src[1]})
    return out
