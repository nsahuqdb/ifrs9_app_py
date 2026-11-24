"""The daily input folders: one parent folder, one sub-folder per date.

    ifrs_inputs/
      2026-11-23/   the extracts as saved that day (.xlsx, .xls, .csv ...)
      2026-11-24/

The files are read where they are, as they are: nothing is copied, unzipped
or renamed. A folder is matched to a date by its name, in any of the usual
ways of writing one (2026-11-24, 20261124, 24-11-2026, 24.11.2026,
24Nov2026, IN_2026-11-24 ...), directly under the parent or one level down
(ifrs_inputs/2026/2026-11-24). Day before month when a name could be either.
The files may also sit one folder further in (2026-11-24/IN/...).
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_SEP = r"[-_. ]?"
_YMD = re.compile(rf"(?<!\d)(20\d\d){_SEP}(\d\d){_SEP}(\d\d)(?!\d)")
_DMY = re.compile(rf"(?<!\d)(\d\d){_SEP}(\d\d){_SEP}(20\d\d)(?!\d)")
_DMONY = re.compile(rf"(?<!\d)(\d{{1,2}}){_SEP}([a-z]{{3}})[a-z]*{_SEP}(20\d\d)(?!\d)", re.I)


def _valid(y, m, d) -> date | None:
    try:
        return date(int(y), int(m), int(d))
    except (TypeError, ValueError):
        return None


def folder_date(name: str) -> date | None:
    """The date a folder's name gives, or None."""
    for m in _YMD.finditer(name):
        if got := _valid(*m.groups()):
            return got
    for m in _DMY.finditer(name):
        d, mo, y = m.groups()
        if got := _valid(y, mo, d):
            return got
    for m in _DMONY.finditer(name):
        d, mon, y = m.groups()
        if mon.lower()[:3] in _MONTHS and (got := _valid(y, _MONTHS[mon.lower()[:3]], d)):
            return got
    return None


def _expected_stems() -> set[str]:
    from ifrs9qdb.acquisition import expected_input_files
    return {Path(f).stem.lower() for f in expected_input_files()}


def files_found(d: Path) -> int:
    """How many of the 12 extracts a folder holds, by name whatever the
    extension (as the run finds them)."""
    if not d.is_dir():
        return 0
    try:
        stems = {p.stem.lower() for p in d.iterdir()
                 if p.is_file() and not p.name.startswith(("~$", "."))}
    except OSError:
        return 0
    return len(_expected_stems() & stems)


def date_folders(root: Path | None) -> list[dict]:
    """Every dated folder under the parent, newest date first:
    {date, name, path, found, expected, complete}. When two folders give the
    same date, the one with more of the files is used."""
    if not root or not Path(root).is_dir():
        return []
    root = Path(root)
    n_expected = len(_expected_stems())
    best: dict[date, dict] = {}

    def consider(p: Path):
        d = folder_date(p.name)
        if d is None:
            return False
        n = files_found(p)
        if n == 0:
            # the files one folder further in (2026-11-24/IN/...)
            try:
                inner = [(files_found(x), x) for x in p.iterdir() if x.is_dir()]
            except OSError:
                inner = []
            if inner:
                k, x = max(inner, key=lambda t: t[0])
                if k:
                    n, p = k, x
        row = {"date": d.isoformat(), "name": str(p.relative_to(root)), "path": str(p),
               "found": n, "expected": n_expected, "complete": n >= n_expected}
        old = best.get(d)
        if old is None or n > old["found"]:
            best[d] = row
        return True

    try:
        subs = sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return []
    for p in subs:
        if consider(p):
            continue
        # a year or month folder: look one level down
        try:
            for q in sorted(x for x in p.iterdir() if x.is_dir()):
                consider(q)
        except OSError:
            pass
    return [best[d] for d in sorted(best, reverse=True)]


def folder_for(root: Path | None, day: str | date) -> dict | None:
    """The folder for a date, or None."""
    d = day if isinstance(day, date) else datetime.fromisoformat(str(day)[:10]).date()
    return next((r for r in date_folders(root) if r["date"] == d.isoformat()), None)
