"""The regulatory side of the assistant: the documents in docs/regulatory,
read on this machine, and the benchmarks QDB's settings are compared with.

**The folder.** Official texts (IFRS 9, the Basel Framework, QCB circulars and
instructions, EBA / Bank of England / Federal Reserve / FINMA stress test
documents ...) are put in ``docs/regulatory`` by the user. Their text is
extracted here -- PDF page by page, Word, Markdown or plain text -- and kept in
``docs/regulatory/.index`` so a document is read once; nothing leaves the
machine. A passage is cited by file and page.

**The benchmarks.** For the settings a reviewer compares -- collateral
haircuts, LGD, CCF, default and Stage 2 thresholds, cure, scenarios,
measurement -- each regulator's value with its paragraph, beside QDB's value
read from the run's frozen configuration (or the live one). The regulators'
values were checked against the texts named in ``ref``; QCB values that can
only be read in the circular say so.
"""
from __future__ import annotations

import json
import re
import zipfile
from functools import lru_cache
from pathlib import Path

import pandas as pd

from .knowledge import APP_ROOT, Chunk, tokens

REG_DIR = APP_ROOT / "docs" / "regulatory"
_CACHE = REG_DIR / ".index"
READABLE = (".pdf", ".docx", ".md", ".txt", ".htm", ".html")


# ------------------------------------------------------------ the folder --
def _title(path: Path) -> str:
    return re.sub(r"[_]+", " ", path.stem).strip()


def _pdf_pages(path: Path) -> list[str]:
    from pypdf import PdfReader               # in the app's requirements
    reader = PdfReader(str(path))
    return [(pg.extract_text() or "") for pg in reader.pages]


def _docx_text(path: Path) -> list[str]:
    """A Word file's paragraphs, without python-docx: the text runs of
    word/document.xml, a page per ~3,000 characters for citing."""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    paras = [re.sub(r"<[^>]+>", "", p) for p in re.split(r"</w:p>", xml)]
    text = "\n".join(p for p in paras if p.strip())
    return [text[i:i + 3000] for i in range(0, len(text), 3000)] or [""]


def _plain(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in (".htm", ".html"):
        text = re.sub(r"<[^>]+>", " ", text)
    return [text[i:i + 3000] for i in range(0, len(text), 3000)] or [""]


def _read(path: Path) -> tuple[list[str], str]:
    """(text per page, problem) -- a document that cannot be read is listed
    with the reason, never silently dropped."""
    try:
        suf = path.suffix.lower()
        if suf == ".pdf":
            pages = _pdf_pages(path)
            if not any(p.strip() for p in pages):
                return [], "no text layer (a scan): needs OCR before it can be searched"
            return pages, ""
        if suf == ".docx":
            return _docx_text(path), ""
        return _plain(path), ""
    except ImportError:
        return [], "the PDF reader (pypdf) is not installed: restart with start_ifrs9.bat"
    except Exception as exc:                   # a damaged or protected file
        return [], f"could not be read ({type(exc).__name__})"


def _cached(path: Path) -> tuple[list[str], str]:
    _CACHE.mkdir(parents=True, exist_ok=True)
    key = re.sub(r"[^A-Za-z0-9._-]+", "_", str(path.relative_to(REG_DIR)))
    c = _CACHE / f"{key}.json"
    stamp = [path.stat().st_size, path.stat().st_mtime_ns]
    if c.is_file():
        try:
            d = json.loads(c.read_text(encoding="utf-8"))
            if d.get("stamp") == stamp:
                return d["pages"], d.get("problem", "")
        except Exception:
            pass
    pages, problem = _read(path)
    try:
        c.write_text(json.dumps({"stamp": stamp, "pages": pages, "problem": problem}),
                     encoding="utf-8")
    except Exception:
        pass
    return pages, problem


def folder_files() -> list[Path]:
    if not REG_DIR.is_dir():
        return []
    return sorted(p for p in REG_DIR.rglob("*")
                  if p.is_file() and p.suffix.lower() in READABLE
                  and ".index" not in p.parts and p.name.lower() != "readme.md")


def stamp() -> tuple:
    return tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in folder_files())


@lru_cache(maxsize=2)
def _folder(st: tuple) -> tuple[list[Chunk], list[dict]]:
    chunks, listing = [], []
    for p in folder_files():
        pages, problem = _cached(p)
        listing.append({"document": p.name, "pages": len(pages), "problem": problem})
        for i, text in enumerate(pages, 1):
            t = re.sub(r"[ \t]+", " ", text).strip()
            if len(t) < 40:
                continue
            chunks.append(Chunk("", "reg", p.name, _title(p), f"page {i}", t[:6000], i,
                                where=f"docs/regulatory/{p.relative_to(REG_DIR).as_posix()}"))
    return chunks, listing


def folder() -> tuple[list[Chunk], list[dict]]:
    """The folder's passages (one per page) and what is in it."""
    return _folder(stamp())


# --------------------------------------------------- QDB's live settings --
def _read_csv(p: Path) -> pd.DataFrame:
    return pd.read_csv(p, comment="#")


def qdb_settings(config_dir: Path | None, static_dir: Path | None) -> dict:
    """The settings the benchmarks compare, from a run's frozen config (or
    the live one): haircut by collateral type, LGD base and floor, Stage 2
    DPD threshold, number of scenarios and weight mode, Stage 3 method."""
    import yaml
    out: dict = {"haircut": {}, "where": ""}
    if static_dir and (static_dir / "collateral_types.csv").is_file():
        ct = _read_csv(static_dir / "collateral_types.csv")
        out["haircut"] = {str(r["description"]).strip().lower(): float(r["haircut_general"])
                          for _, r in ct.iterrows() if pd.notna(r.get("haircut_general"))}
    if static_dir and (static_dir / "staging_thresholds.csv").is_file():
        stt = _read_csv(static_dir / "staging_thresholds.csv")
        m = dict(zip(stt["key"].astype(str), stt["value"]))
        try:
            out["dpd_stage2"] = float(m.get("dpd_stage2_threshold_days"))
        except (TypeError, ValueError):
            pass
        try:
            out["maturity_extension_days"] = float(m.get("maturity_extension_days"))
        except (TypeError, ValueError):
            pass
    if static_dir and (static_dir / "scenario_severity.csv").is_file():
        out["n_scenarios"] = len(_read_csv(static_dir / "scenario_severity.csv"))
    if static_dir and (static_dir / "ttc_pd_table.csv").is_file():
        tp = _read_csv(static_dir / "ttc_pd_table.csv")
        pos = pd.to_numeric(tp["ttc_pd"], errors="coerce")
        out["min_ttc_pd_internal"] = float(pos[tp["rating_type"].astype(str) == "1"].min()) \
            if (tp["rating_type"].astype(str) == "1").any() else None
    if config_dir and (config_dir / "model.yml").is_file():
        mdl = yaml.safe_load((config_dir / "model.yml").read_text(encoding="utf-8")) or {}
        ecl = mdl.get("ecl") or {}
        out["lgd_base"] = float(ecl.get("lgd_base", 0.45))
        out["lgd_floor"] = float(ecl.get("lgd_unsecured_floor", 0.5))
        out["stage3_method"] = str(ecl.get("stage3_method", "full_outstanding"))
    if config_dir and (config_dir / "model_inputs.yml").is_file():
        mi = yaml.safe_load((config_dir / "model_inputs.yml").read_text(encoding="utf-8")) or {}
        out["weights_mode"] = str((mi.get("internal_scenario_weights") or {}).get("mode", ""))
    return out


def _pct(v) -> str:
    if v is None:
        return "n/a"
    s = f"{100 * v:.4f}".rstrip("0").rstrip(".")
    return f"{s}%"


def _hc(q: dict, *names: str) -> str:
    """QDB's haircut for the first collateral type found, and what it means."""
    for n in names:
        v = q["haircut"].get(n.lower())
        if v is not None:
            counted = "nothing counted" if v >= 1 else ("counted in full" if v == 0
                                                        else f"{_pct(1 - v)} of value counted")
            return f"{_pct(v)} haircut ({counted})"
    return "not in collateral_types.csv (unmapped: nothing counted)"


# --------------------------------------------------------- benchmarks -----
# topic, item, qdb(q) -> text, then each benchmark with its reference. The
# Basel values are the BIS consolidated framework (CRE20, CRE22, CRE32); IFRS 9
# the standard's paragraphs; QCB from the methodology pack's quotes of
# Circular 9/2017 and KPMG's summary of the QCB instructions (2018), or "see
# the circular" where only the circular has the value.
def _rows(q: dict) -> list[dict]:
    lgd = q.get("lgd_base", 0.45)
    fl = q.get("lgd_floor", 0.5)
    dpd = q.get("dpd_stage2", 60)
    R = []

    def row(topic, item, qdb, basel="", basel_ref="", ifrs9="", ifrs9_ref="", qcb="", qcb_ref="",
            other="", note=""):
        R.append({"topic": topic, "item": item, "QDB": qdb, "Basel": basel, "Basel ref": basel_ref,
                  "IFRS 9": ifrs9, "IFRS 9 ref": ifrs9_ref, "QCB": qcb, "QCB ref": qcb_ref,
                  "other": other, "note": note})

    qcb_hc = "eligible collateral list with regulatory haircuts in the IFRS 9 instructions"
    qcb_hc_ref = "QCB Circular 9/2017 (KPMG summary, p.34); values: the circular in docs/regulatory"
    ifrs_coll = "collateral cash flows, net of costs to obtain and sell, are part of the cash shortfalls"
    # collateral -------------------------------------------------------------
    row("collateral", "Cash collateral / collateral account", _hc(q, "Cash Collateral", "COLLATERAL ACCOUNT"),
        "0% (cash in the same currency); F-IRB: LGD 0% on the covered part", "CRE22.49; CRE32.11",
        ifrs_coll, "B5.5.55", qcb_hc, qcb_hc_ref,
        note="QDB gives cash no value; Basel counts it in full")
    row("collateral", "Bank guarantee", _hc(q, "LETTER OF GUARANTEE-BANK"),
        "a guarantee is recognised by putting the guarantor's risk in place of the borrower's, not by a haircut",
        "CRE22 (guarantees)", ifrs_coll, "B5.5.55", qcb_hc, qcb_hc_ref)
    row("collateral", "Residential property", _hc(q, "Residential Property"),
        "F-IRB: LGD 20% on the secured part, with a 40% haircut on the value", "CRE32.10–32.11",
        ifrs_coll, "B5.5.55", qcb_hc, qcb_hc_ref,
        note="Basel's standardised approach treats real estate through LTV-based risk weights, not a haircut")
    row("collateral", "Commercial property", _hc(q, "Commercial Property"),
        "F-IRB: LGD 20% on the secured part, with a 40% haircut on the value", "CRE32.10–32.11",
        ifrs_coll, "B5.5.55", qcb_hc, qcb_hc_ref)
    row("collateral", "Farm property", _hc(q, "FARM PROPERTY"),
        "real estate: F-IRB LGD 20%, haircut 40%", "CRE32.10–32.11", ifrs_coll, "B5.5.55", qcb_hc, qcb_hc_ref)
    row("collateral", "Listed shares", _hc(q, "Share - Local", "Share - Foreign", "Equity"),
        "20% (main-index equities and gold); 30% (other listed equities)", "CRE22.49",
        ifrs_coll, "B5.5.55", qcb_hc, qcb_hc_ref)
    row("collateral", "Bonds", _hc(q, "Local Bond", "Foreign Bond"),
        "by issuer, rating and maturity: sovereigns AAA to AA- 0.5% (up to 1 year) to 12% (over 10 years), "
        "A+ to BBB- 1% to 20%, BB 15%; other issuers AAA to AA- 1% (up to 1 year), 3% (1-3 years), 6% (5-10 years)",
        "CRE22.49", ifrs_coll, "B5.5.55", qcb_hc, qcb_hc_ref)
    row("collateral", "Gold / precious metal", _hc(q, "Precious Metal"), "20%", "CRE22.49",
        ifrs_coll, "B5.5.55", qcb_hc, qcb_hc_ref)
    row("collateral", "Machinery, goods, other physical", _hc(q, "Machinery Detail", "GOODS"),
        "F-IRB: LGD 25% on the secured part, with a 40% haircut on the value", "CRE32.11",
        ifrs_coll, "B5.5.55", qcb_hc, qcb_hc_ref)
    row("collateral", "Personal / corporate guarantees, cheques, insurance, documents",
        _hc(q, "Personal Guarantee", "Corporate Guarantee"),
        "guarantees only from eligible guarantors (substitution); ineligible collateral: 100% haircut",
        "CRE22 (guarantees); CRE32.11", ifrs_coll, "B5.5.55", qcb_hc, qcb_hc_ref)
    row("collateral", "Currency mismatch", "no extra haircut",
        "8% on top when collateral and exposure are in different currencies", "CRE22.52",
        qcb=qcb_hc, qcb_ref=qcb_hc_ref)
    # LGD --------------------------------------------------------------------
    row("lgd", "LGD on the unsecured part", _pct(lgd),
        "F-IRB senior unsecured: 40% (non-financial corporates), 45% (financial institutions); "
        "subordinated 75%", "CRE32.6–32.7", "own estimate (unbiased, probability-weighted)", "5.5.17",
        "45% minimum for non-subordinated unsecured claims", "methodology pack slide 71 (\"Basel & QCB\")",
        note="the pack's 45% is the earlier Basel value for all senior unsecured claims")
    row("lgd", "Lowest LGD possible", f"{_pct(lgd * fl)} ({_pct(lgd)} x at least {_pct(fl)} unsecured)",
        "A-IRB floors: 25% unsecured; fully secured: financial 0%, receivables 10%, real estate 10%, "
        "other physical 15%", "CRE32.16", "no floor; collateral cash flows included", "B5.5.55",
        note="collateral above about half the balance does not lower QDB's LGD")
    row("lgd", "How collateral enters", "LGD = base x max(floor, unsecured share); collateral net of haircut, "
        "allocated per facility",
        "LGD* = LGD(unsecured) x E(unsecured)/E + LGD(secured) x E(secured)/E, exposure grossed up by its own "
        "haircut", "CRE32.10", "expected cash shortfalls, incl. collateral", "B5.5.55")
    row("lgd", "Stage 3", "100% of the balance" if q.get("stage3_method", "full_outstanding") ==
        "full_outstanding" else q.get("stage3_method"),
        "", "", "lifetime ECL; collateral cash flows count", "5.5.3; B5.5.55",
        note="QDB recognises no recovery on defaulted balances")
    # EAD / CCF --------------------------------------------------------------
    row("ccf", "Letters of guarantee (performance, bid bonds)",
        "amount x CCF in the extract; pack CCF 50% for bank guarantees",
        "50% (transaction-related contingent items); 100% (guarantees of indebtedness)", "CRE20.97; CRE20.95",
        "ECL on financial guarantee contracts and loan commitments", "5.5.1")
    row("ccf", "Letters of credit", "amount x CCF in the extract; pack CCF 20%",
        "20% (short-term self-liquidating trade letters of credit)", "CRE20.99")
    row("ccf", "Al Dhameen (guarantee of partner-bank financing)", "full amount (CCF 100%) in the extract; "
        "the pack says 50%", "100% (direct credit substitutes, general guarantees of indebtedness)", "CRE20.95")
    row("ccf", "Undrawn commitments", "on-balance facilities: no drawdown (DDF 0, pack slide 79)",
        "40% (commitments); 10% (unconditionally cancellable)", "CRE20.98; CRE20.100",
        "revolving facilities: the period of actual exposure, which can exceed the contract", "5.5.20")
    # staging and default ----------------------------------------------------
    row("staging", "Default (Stage 3)", "worst DPD above 90 at customer level, or the default flag",
        "more than 90 days past due, or a defaulted borrower", "CRE20.104",
        "rebuttable presumption: default no later than 90 days past due", "B5.5.37",
        "90 DPD, with QCB's irregularities (instalment unpaid 3 months, limit exceeded by 10%, insolvency ...)",
        "methodology pack slide 84")
    row("staging", "Stage 2 backstop (days past due)", f"worst DPD above {dpd:g} days",
        "", "", "rebuttable presumption: significant increase at more than 30 days past due", "5.5.11; B5.5.19",
        "rebuttal allowed with supporting analysis", "methodology pack slide 92",
        note="QDB rebutted 30 DPD with a forward-flow analysis (pack slide 93), redone yearly")
    row("staging", "Rating deterioration", "not used: no rating at origination",
        "", "", "compare default risk now with default risk at initial recognition", "5.5.9",
        "two-notch downgrade threshold", "methodology pack slide 90",
        other="EBA 2025 stress test: three-fold rise in lifetime PD since origination (para. 56)")
    row("staging", "Watchlist, restructuring", "Stage 2 (pack slide 90: restructuring for financial difficulty)",
        "", "", "a non-exhaustive list of indicators of increased credit risk; modified assets compared with "
        "the original terms", "B5.5.17; 5.5.12")
    row("staging", "Low credit risk", "no rating-based test for investments; pack: AAA and AA debt securities",
        "", "", "no significant increase assumed when credit risk is low (investment grade is one example)",
        "5.5.10; B5.5.22–23", "AAA and AA", "methodology pack slide 87",
        other="EBA 2025 stress test: 1-year PD below 0.30% (para. 56)")
    row("staging", "Cure (probation)", "none in the tool: each quarter is staged from its own DPD and flags",
        "", "", "", "", "12-month cooling-off period to move back from Stage 3/2 to Stage 2/1",
        "KPMG summary of QCB instructions, p.34; pack slide 92 (12 months, QCB approval)")
    row("staging", "Level", "customer: worst DPD and flags; contagion to all the customer's facilities", "", "",
        "", "", "obligor-level staging; exceptions need QCB approval", "KPMG summary, p.34")
    # scenarios and measurement ----------------------------------------------
    row("measurement", "Number of scenarios", f"{q.get('n_scenarios', 5)} weighted scenarios",
        "", "", "probability-weighted; at least two outcomes when scenarios are modelled", "5.5.17; B5.5.42",
        "at least three, at most five", "KPMG summary, p.34; methodology pack slide 108")
    row("measurement", "Scenario weights", f"mode: {q.get('weights_mode') or 'n/a'} (V2: from the forecast's "
        "place on the history)", "", "", "unbiased, probability-weighted", "5.5.17")
    row("measurement", "Horizon", f"to contractual maturity; a matured facility is extended by "
        f"{q.get('maturity_extension_days', 365):g} days", "", "",
        "maximum contractual period, incl. extension options", "5.5.19; B5.5.38")
    row("measurement", "Discounting", "monthly at the contract's EIR", "", "",
        "original effective interest rate (or an approximation)", "B5.5.44")
    row("measurement", "PD floor", f"none (lowest internal TTC PD {_pct(q.get('min_ttc_pd_internal'))})",
        "0.05% for corporate and bank exposures (not sovereigns)", "CRE32.4",
        "possibility of loss always reflected, even if low", "5.5.18")
    return R


STRESS = [
    {"who": "EBA (EU-wide, 2025)", "horizon": "3 years (2025–2027), from year-end 2024",
     "balance sheet": "static: maturing exposures replaced like for like",
     "credit risk": "point-in-time 12-month stage transition rates and lifetime loss rates under the "
                    "scenario; Stage 1→2 at a three-fold lifetime PD rise; no cures out of Stage 3; "
                    "no release of Stage 3 provisions; real estate collateral follows the house price path",
     "ref": "EBA 2025 EU-wide stress test, Methodological Note, paras 24, 33, 56, 66–68, 84–93, Box 2"},
    {"who": "Bank of England (Bank Capital Stress Test, 2025)", "horizon": "5 years, from end-2024",
     "balance sheet": "not stated on the key elements page",
     "credit risk": "one severe scenario: UK GDP -5%, unemployment peak 8.5% (quarter 9), house prices -28%, "
                    "commercial property -50% from the 2022 peak (about -35% from the start), Bank Rate 8%; "
                    "first test after the IFRS 9 transitional arrangements ended",
     "ref": "BoE, Key elements of the 2025 Bank Capital Stress Test"},
    {"who": "Federal Reserve (supervisory stress test, 2026)", "horizon": "9 quarters (2026Q1–2028Q1)",
     "balance sheet": "see the 2026 Supervisory Stress Test Methodology",
     "credit risk": "severely adverse: unemployment +5.5 points to 10%, GDP -4.6%, house prices -30%, "
                    "commercial real estate -39%, equities -58%",
     "ref": "Federal Reserve, 2026 Stress Test Results (June 2026), introduction"},
    {"who": "FINMA", "horizon": "not stated",
     "balance sheet": "not stated",
     "credit risk": "whole-bank tests and portfolio tests (e.g. mortgage credit risk, interest rate risk), run "
                    "on several institutions to compare; FINMA can order risk reduction or more capital",
     "ref": "FINMA, Supervisory instruments: stress tests"},
    {"who": "Basel Committee", "horizon": "principles, no parameters",
     "balance sheet": "", "credit risk": "stress testing principles on objectives, governance, policies, "
                                         "processes, methodology, resources and documentation",
     "ref": "BCBS, Stress testing principles (d450, October 2018)"},
    {"who": "QCB", "horizon": "ICAAP: 5 years",
     "balance sheet": "ICAAP: base, gross stress and net stress after management actions",
     "credit risk": "sudden and sustained shocks; Financial Stability Review: sudden NPL shocks and a "
                    "break-even test; no prescribed method for stressing provisions",
     "ref": "Stress testing methodology, chapter 6; QCB ICAAP instructions in docs/regulatory"},
    {"who": "QDB (this tool)", "horizon": "Method 1: today; Method 2: 5 years",
     "balance sheet": "static: no new loans, balances and schedules unchanged",
     "credit risk": "the booked ECL's PD model under the scenario; QDB's own rating and stage migration "
                    "matrices (Method 2); property collateral follows the scenario; no management actions",
     "ref": "Stress testing methodology, chapters 1–5"},
]

TOPICS = {
    "collateral": ("collateral", "haircut", "security", "property", "guarantee", "cash", "shares", "bond", "gold"),
    "lgd": ("lgd", "loss given default", "recovery", "floor", "unsecured"),
    "ccf": ("ccf", "conversion", "off balance", "off-balance", "guarantee", "letter of credit", "commitment",
            "ead", "al dhameen"),
    "staging": ("stage", "staging", "sicr", "default", "dpd", "days past due", "cure", "probation",
                "low credit risk", "watchlist", "restructur", "contagion", "notch"),
    "measurement": ("scenario", "weight", "horizon", "discount", "eir", "pd floor", "maturity"),
    "stress": ("stress", "eba", "bank of england", "boe", "fed", "federal reserve", "finma", "ccar", "dfast",
               "icaap"),
}


def topic_of(text: str) -> list[str]:
    t = str(text or "").lower()
    return [k for k, words in TOPICS.items() if any(w in t for w in words)]


def benchmark_rows(q: dict, topic: str | None = None) -> list[dict]:
    rows = _rows(q)
    if topic and topic != "all":
        rows = [r for r in rows if r["topic"] == topic]
    return rows


def reg_tokens(text: str) -> list[str]:
    return tokens(text)
