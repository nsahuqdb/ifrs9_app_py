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


# ------------------------------------------------------------------ tables --
import pandas as pd  # noqa: E402


def test_formatted_amounts_read_back_as_numbers():
    s = pd.Series(["10,000,000", "108,000,000", "80,000,000", "—"])
    num, dec, pct_, grouped = ui._text_number("Exposure", s)
    assert num.tolist()[:3] == [10_000_000, 108_000_000, 80_000_000]
    assert pd.isna(num.iloc[3]) and dec == 0 and not pct_ and grouped
    num, dec, pct_, _ = ui._text_number("share", pd.Series(["1.50%", "12.00%"]))
    assert num.tolist() == [1.5, 12.0] and dec == 2 and pct_


def test_small_counts_are_numbers_ids_are_not():
    num, _, _, grouped = ui._text_number("top_n", pd.Series(["10", "25", "100"]))
    assert num.tolist() == [10, 25, 100] and not grouped
    assert ui._text_number("customer", pd.Series(["1,234"])) is None
    assert ui._text_number("value", pd.Series(["548840", "601233"])) is None
    assert ui._text_number("rating", pd.Series(["QDB 4", "A2"])) is None


def test_the_plain_table_gets_numbers_and_a_format():
    df = pd.DataFrame({"customer": ["1", "2"], "ecl": ["1,000", "250"]})
    out, cfg = ui._native_numbers(df, None)
    assert out["ecl"].tolist() == [1000, 250]
    assert cfg["ecl"]["type_config"]["format"] == "%,.0f"
    assert out["customer"].tolist() == ["1", "2"]


def test_a_customer_column_gets_its_name(monkeypatch):
    import api
    monkeypatch.setattr(api, "customer_names", lambda: {"548840": "Alpha", "7": "Beta"})
    df = pd.DataFrame({"customer": [548840.0, 7, 9], "ecl": [1, 2, 3]})
    out = ui.with_names(df)
    assert list(out.columns) == ["customer", "Customer name", "ecl"]
    assert out["Customer name"].tolist() == ["Alpha", "Beta", ""]
    named = pd.DataFrame({"customer": ["7"], "name": ["x"]})
    assert list(ui.with_names(named).columns) == ["customer", "name"]
    other = pd.DataFrame({"customer": ["C1 — Alpha"]})
    assert list(ui.with_names(other).columns) == ["customer"]


def test_column_groups_keep_the_order():
    defs = [{"field": f} for f in ("id", "e0", "e1", "c0", "c1")]
    out = ui._group_columns(defs, {"Exposure": ["e0", "e1"], "ECL": ["c0", "c1"]})
    assert [d.get("field") or d["headerName"] for d in out] == ["id", "Exposure", "ECL"]
    assert [k["field"] for k in out[1]["children"]] == ["e0", "e1"]


def test_missing_packages_are_found(tmp_path):
    app = tmp_path / "app"
    eng = tmp_path / "ifrs9qdb_py"
    app.mkdir()
    eng.mkdir()
    (app / "pyproject.toml").write_text(
        '[project]\nname="x"\ndependencies=["ifrs9qdb>=9", "pandas>=1", '
        '"no-such-package-qdb>=1"]\n')
    (eng / "pyproject.toml").write_text(
        '[project]\nname="ifrs9qdb"\ndependencies=[]\n'
        '[project.optional-dependencies]\nexcel=["another-missing-qdb"]\n')
    assert ui.missing_packages(app) == ["no-such-package-qdb>=1", "another-missing-qdb"]
