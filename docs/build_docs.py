"""Build the Word copies of the documents in this folder.

    python docs/build_docs.py            # every .md here
    python docs/build_docs.py user_manual

Needs pandoc (3.x) and python-docx. The Markdown is the source; the .docx is
generated and committed so the Help pages can offer it without pandoc on the
server. reference.docx carries the styles (QDB plum headings in Alexandria,
Calibri body).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

HERE = Path(__file__).resolve().parent
MAX_W, MAX_H = Cm(17), Cm(23)


def _borders(table) -> None:
    tblPr = table._tbl.tblPr
    b = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:val"), "single")
        e.set(qn("w:sz"), "4")
        e.set(qn("w:color"), "D5CCDB")
        b.append(e)
    tblPr.append(b)


def _shade(cell, fill: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tcPr.append(shd)


def _polish(path: Path) -> None:
    doc = Document(str(path))
    for t in doc.tables:
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        _borders(t)
        for i, row in enumerate(t.rows):
            for c in row.cells:
                if i == 0:
                    _shade(c, "EFE7F3")
                for p in c.paragraphs:
                    p.paragraph_format.space_after = Pt(2)
                    for r in p.runs:
                        r.font.size = Pt(9)
                        if i == 0:
                            r.font.bold = True
    for shape in doc.inline_shapes:
        w, h = shape.width, shape.height
        k = min(1.0, MAX_W / w, MAX_H / h)
        shape.width, shape.height = int(w * k), int(h * k)
    # Word fills the table of contents when the file is opened (it asks once).
    settings = doc.settings.element
    if settings.find(qn("w:updateFields")) is None:
        u = OxmlElement("w:updateFields")
        u.set(qn("w:val"), "true")
        settings.append(u)
    doc.save(str(path))


def build(stem: str) -> Path:
    src, out = HERE / f"{stem}.md", HERE / f"{stem}.docx"
    subprocess.run(["pandoc", str(src), "-o", str(out), "--toc", "--toc-depth=2",
                    "--resource-path", str(HERE),
                    "--reference-doc", str(HERE / "reference.docx"),
                    "-f", "markdown+tex_math_dollars+pipe_tables"],
                   check=True, cwd=HERE)
    _polish(out)
    return out


if __name__ == "__main__":
    stems = sys.argv[1:] or [p.stem for p in sorted(HERE.glob("*.md"))]
    for s in stems:
        print(build(s))
