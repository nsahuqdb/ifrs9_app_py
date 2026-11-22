"""The reference documents under Help: the user manual and the two
methodologies, read from docs/ and drawn on screen.

A document is Markdown with a YAML front matter block (title, subtitle,
author, date), the same file pandoc turns into the Word copy offered for
download. On screen it is split at its top-level headings so one chapter can
be read at a time, searched, and its pictures drawn with st.image rather than
as broken relative links.
"""
from __future__ import annotations

import re
from pathlib import Path

import streamlit as st

from ui import caption, page_setup

DOCS = Path(__file__).resolve().parents[1] / "docs"
IMG = re.compile(r"^\s*!\[(?P<alt>[^\]]*)\]\((?P<src>[^)\s]+)\)\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")


def _front_matter(text: str) -> tuple[dict, str]:
    """The YAML header and the body after it."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    meta = {}
    for line in text[3:end].strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, text[end + 4:].lstrip("\n")


def _chapters(body: str) -> list[tuple[str, str]]:
    """(title, text) per top-level heading, ignoring '#' inside code."""
    out, title, buf, code = [], "", [], False
    for line in body.splitlines():
        if FENCE.match(line):
            code = not code
        if not code and line.startswith("# "):
            if buf and (title or "".join(buf).strip()):
                out.append((title, "\n".join(buf)))
            title, buf = line[2:].strip(), [line]
        else:
            buf.append(line)
    if buf:
        out.append((title, "\n".join(buf)))
    return out


def _sections(chapter: str) -> list[str]:
    """A chapter cut at its second-level headings (for search hits)."""
    parts, buf, code = [], [], False
    for line in chapter.splitlines():
        if FENCE.match(line):
            code = not code
        if not code and line.startswith("## ") and buf:
            parts.append("\n".join(buf))
            buf = []
        buf.append(line)
    if buf:
        parts.append("\n".join(buf))
    return parts


def _render(text: str) -> None:
    """Markdown with each heading one level down (the page has its own
    title) and each picture drawn from docs/."""
    buf, code = [], False

    def flush():
        if "".join(buf).strip():
            st.markdown("\n".join(buf))
        buf.clear()

    for line in text.splitlines():
        if FENCE.match(line):
            code = not code
        m = None if code else IMG.match(line)
        if m:
            flush()
            path = DOCS / m["src"]
            if path.is_file():
                st.image(str(path), caption=m["alt"] or None, use_container_width=True)
            else:
                caption(f"(picture missing: {m['src']})")
            continue
        if not code and line.startswith("#"):
            line = "#" + line
        buf.append(line)
    flush()


def show(stem: str, blurb: str) -> None:
    """Draw docs/<stem>.md with its chapter picker, search and downloads."""
    md_path = DOCS / f"{stem}.md"
    if not md_path.is_file():
        page_setup("Document not found")
        st.error(f"{md_path} is missing from this deployment.")
        return
    meta, body = _front_matter(md_path.read_text(encoding="utf-8"))
    page_setup(meta.get("title", stem), meta.get("subtitle") or blurb)
    chapters = _chapters(body)
    titles = [t for t, _ in chapters if t]

    c1, c2, c3, c4 = st.columns([4, 3, 1.4, 1.4], vertical_alignment="bottom")
    pick = c1.selectbox("Chapter", ["Whole document"] + titles, key=f"doc_{stem}_ch")
    q = c2.text_input("Search this document", key=f"doc_{stem}_q",
                      placeholder="e.g. overlay, haircut, Stage 2").strip()
    docx = DOCS / f"{stem}.docx"
    if docx.is_file():
        c3.download_button("Word", docx.read_bytes(), file_name=docx.name,
                           mime="application/vnd.openxmlformats-officedocument."
                                "wordprocessingml.document",
                           icon=":material/description:", width="stretch",
                           key=f"doc_{stem}_docx")
    c4.download_button("Markdown", md_path.read_bytes(), file_name=md_path.name,
                       mime="text/markdown", icon=":material/download:",
                       width="stretch", key=f"doc_{stem}_md")
    caption(" · ".join(x for x in (meta.get("author"), meta.get("date")) if x))

    if q:
        ql = q.lower()
        hits = [(t, s) for t, ch in chapters for s in _sections(ch) if ql in s.lower()]
        if not hits:
            st.info(f"Nothing in this document mentions “{q}”.")
            return
        caption(f"{len(hits)} section(s) mention “{q}”.")
        for t, s in hits:
            with st.container(border=True):
                if not s.lstrip().startswith("# "):
                    caption(t)
                _render(s)
        return

    if pick == "Whole document":
        with st.expander("Contents", expanded=False, icon=":material/toc:"):
            st.markdown("\n".join(f"- {t}" for t in titles))
            caption("Pick a chapter above to read it on its own.")
        for _, text in chapters:
            _render(text)
    else:
        _render(next(text for t, text in chapters if t == pick))
        i = titles.index(pick)
        b1, b2 = st.columns(2)

        def go(t: str) -> None:          # a callback: runs before the picker is drawn
            st.session_state[f"doc_{stem}_ch"] = t

        if i > 0:
            b1.button(f"← {titles[i - 1]}", key=f"doc_{stem}_prev",
                      on_click=go, args=(titles[i - 1],))
        if i < len(titles) - 1:
            b2.button(f"{titles[i + 1]} →", key=f"doc_{stem}_next",
                      on_click=go, args=(titles[i + 1],))
