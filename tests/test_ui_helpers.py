"""The interface's own helpers: pure functions, checked without a backend."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "frontend"))

import ui  # noqa: E402


def test_markdown_is_escaped_before_it_is_formatted():
    """A finding's text is data: a tag in it is shown, not obeyed, and a
    Windows path keeps its backslashes."""
    got = ui.md(r"**blocked** <script>x</script> `C:\IFRS9\input`")
    assert got.startswith("<b>blocked</b> &lt;script&gt;")
    assert r"<code>C:\IFRS9\input</code>" in got


def test_a_run_reads_as_id_date_type_and_status():
    assert ui.run_label({"run_id": "run_00007", "portfolio_date": "2026-06-09",
                         "run_type": "official", "status": "approved"}) == \
        "run_00007 · 09 Jun 2026 · Official · approved"
    # R writes m/d/Y; an unofficial run's status says nothing new
    assert ui.run_label({"run_id": "run_00002", "portfolio_date": "6/9/2026",
                         "run_type": "unofficial", "status": "unofficial"}) == \
        "run_00002 · 09 Jun 2026 · Unofficial"
    assert ui.run_label({"run_id": "run_00001", "portfolio_date": "NA"}) == "run_00001"


def test_an_accepted_finding_is_counted_apart_from_its_severity():
    rows = [{"severity": "ERROR", "effective_severity": "ERROR"},
            {"severity": "ERROR", "effective_severity": "INFO", "suppressed": True},
            {"severity": "WARN"}, {"severity": "INFO"}]
    assert ui.severity_counts(rows) == {"err": 1, "warn": 1, "info": 1,
                                        "muted": 1, "ok": 0}


def test_every_severity_has_a_colour():
    assert [ui.tone_of(s) for s in ("ERROR", "warn", "Info", "PASS", "ACCEPTED",
                                    "SUPPR")] == \
        ["err", "warn", "info", "ok", "muted", "muted"]


def test_an_accepted_finding_says_who_how_and_why():
    assert ui.accepted_note({"accepted_source": "run", "accepted_by": "maker1",
                             "accepted_reason": "two-digit years"}) == \
        "Accepted for this run by **maker1** — two-digit years"
    note = ui.accepted_note({"source": "standing", "accepted_by": "checker1",
                             "reason": "ticket #77", "valid_until": "2099-12-31"})
    assert note == ("Standing suppression approved by **checker1**, valid until "
                    "2099-12-31 — ticket #77")
    assert ui.accepted_note({"severity": "ERROR"}) == ""
