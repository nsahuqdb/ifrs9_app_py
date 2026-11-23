"""What the assistant can read besides the runs: the documents under Help,
the engine's source code and the configuration files.

Everything is cut into sections (a document at its headings, the code at its
functions and classes, a config file as a whole) and searched with BM25, which
needs no model, no network and no extra package. A hit carries where it came
from -- document and section, or file and line -- so an answer can cite it and
the user can open the same place.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = APP_ROOT / "docs"

# Help page per document, so a citation can say where to read it in the app.
HELP_PAGES = {
    "README": "README",
    "user_manual": "Help → User manual",
    "ecl_methodology": "Help → ECL methodology",
    "stress_testing_methodology": "Help → Stress testing methodology",
}

_STOP = set("""a an and are as at be by for from has have how i if in into is it
its of on or that the their then there these this to was were what when where
which who why will with does do can our we you your show me give list tell""".split())


def _stem(w: str) -> str:
    for suf in ("ations", "ation", "ings", "ing", "ies", "ied", "es", "ed", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf in ("ies", "ied") else "")
    return w


def tokens(text: str) -> list[str]:
    """Lower-case words and numbers, stop words out, light stemming; a name in
    snake_case or CamelCase also gives its parts, so `compute_lgd` is found
    by "lgd"."""
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(text))
    out = []
    for w in re.findall(r"[A-Za-z][A-Za-z0-9]*|\d+(?:\.\d+)?", text.replace("_", " ")):
        w = w.lower()
        if w not in _STOP and len(w) > 1:
            out.append(_stem(w))
    return out


@dataclass
class Chunk:
    id: str
    kind: str            # doc | code | config
    source: str          # document stem, module path or file name
    title: str           # document title, or file path
    section: str         # heading, or function/class name
    text: str
    line: int = 1
    where: str = ""      # where to open it in the app (for documents)
    toks: list[str] = field(default_factory=list, repr=False)


# ---------------------------------------------------------------- readers --
def _front_matter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    meta = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"')
    return meta, text[end + 4:]


def _doc_chunks(path: Path) -> list[Chunk]:
    meta, body = _front_matter(path.read_text(encoding="utf-8", errors="replace"))
    title = meta.get("title") or path.stem.replace("_", " ")
    out, head, buf, start, code = [], [], [], 1, False
    lines = body.splitlines()

    def flush(n_end):
        text = "\n".join(buf).strip()
        if text and not re.fullmatch(r"#+ .*", text):
            sec = " › ".join(head) if head else title
            out.append(Chunk("", "doc", path.stem, title, sec, text, start,
                             HELP_PAGES.get(path.stem, f"docs/{path.name}")))

    for i, line in enumerate(lines, 1):
        if line.lstrip().startswith(("```", "~~~")):
            code = not code
        m = None if code else re.match(r"^(#{1,3})\s+(.*)", line)
        if m:
            flush(i)
            level = len(m.group(1))
            head = head[: level - 1] + [m.group(2).strip()]
            buf, start = [line], i
        else:
            buf.append(line)
    flush(len(lines))
    return out


_DEF = re.compile(r"^(def|class|async def)\s+([A-Za-z_][A-Za-z0-9_]*)", re.M)


def _code_chunks(path: Path, root: Path) -> list[Chunk]:
    """Top-level functions and classes, each with its docstring and body (cut
    at 80 lines) -- enough to say what a calculation does and where."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    rel = str(path.relative_to(root))
    lines = text.splitlines()
    starts = [(m.start(), m.group(2)) for m in _DEF.finditer(text)]
    out = []
    mod_doc = re.match(r'\s*(?:#.*\n)*\s*("""|\'\'\')(.*?)\1', text, re.S)
    if mod_doc:
        out.append(Chunk("", "code", rel, rel, "(module)", mod_doc.group(2).strip()[:3000], 1))
    for k, (pos, name) in enumerate(starts):
        line0 = text.count("\n", 0, pos) + 1
        line1 = (text.count("\n", 0, starts[k + 1][0]) if k + 1 < len(starts)
                 else len(lines))
        body = "\n".join(lines[line0 - 1: min(line1, line0 + 79)])
        out.append(Chunk("", "code", rel, rel, name, body, line0))
    return out


def _config_chunks(path: Path, label: str) -> list[Chunk]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    return [Chunk("", "config", path.name, label, path.name, text[:6000], 1)]


def _engine_root() -> Path | None:
    try:
        import ifrs9qdb
        return Path(ifrs9qdb.__file__).resolve().parent
    except Exception:
        return None


def _sources() -> list[Path]:
    paths = sorted(DOCS_DIR.glob("*.md")) if DOCS_DIR.is_dir() else []
    if (APP_ROOT / "README.md").is_file():
        paths.append(APP_ROOT / "README.md")
    eng = _engine_root()
    if eng:
        # a source checkout (src/ifrs9qdb) also has the engine's notes: the
        # methodology issue register, the README
        repo = eng.parent.parent if eng.parent.name == "src" else None
        if repo is not None:
            paths += sorted(repo.glob("*.md"))
        paths += sorted(p for p in eng.rglob("*.py") if "__pycache__" not in p.parts)
    return paths


def _stamp() -> tuple:
    return tuple((str(p), p.stat().st_mtime_ns) for p in _sources() if p.is_file())


# ------------------------------------------------------------------ index --
class Index:
    k1, b = 1.4, 0.75

    def __init__(self, chunks: list[Chunk]):
        for i, c in enumerate(chunks):
            c.id = f"k{i + 1}"
            # the section name counts twice: a heading says what the text is about
            c.toks = tokens(f"{c.section} {c.section} {c.title} {c.text}")
        self.chunks = chunks
        self.df = Counter(t for c in chunks for t in set(c.toks))
        self.n = len(chunks) or 1
        self.avg = sum(len(c.toks) for c in chunks) / self.n
        self.tf = [Counter(c.toks) for c in chunks]

    def search(self, query: str, kinds: tuple[str, ...] = ("doc", "code", "config"),
               k: int = 5) -> list[tuple[float, Chunk]]:
        q = tokens(query)
        if not q:
            return []
        scored = []
        for c, tf in zip(self.chunks, self.tf):
            if c.kind not in kinds:
                continue
            s = 0.0
            for t in q:
                f = tf.get(t)
                if not f:
                    continue
                idf = math.log(1 + (self.n - self.df[t] + 0.5) / (self.df[t] + 0.5))
                s += idf * f * (self.k1 + 1) / (
                    f + self.k1 * (1 - self.b + self.b * len(c.toks) / self.avg))
            if s > 0:
                # the documents explain; the code shows how. For a question that
                # could be either, the explanation comes first.
                scored.append((s * (1.35 if c.kind == "doc" else 1.0), c))
        scored.sort(key=lambda x: -x[0])
        return scored[:k]


@lru_cache(maxsize=2)
def _build(stamp: tuple, config_key: tuple) -> Index:
    chunks: list[Chunk] = []
    eng = _engine_root()
    for p in _sources():
        if p.suffix == ".md":
            chunks += _doc_chunks(p)
        elif eng and p.suffix == ".py":
            chunks += _code_chunks(p, eng.parent)
    for path, label in config_key:
        chunks += _config_chunks(Path(path), label)
    return Index(chunks)


def config_files() -> list[tuple[str, str]]:
    """The live configuration the engine reads (model, per-quarter inputs,
    reference tables), so "what haircut does commercial property get?" can be
    answered from the file itself."""
    try:
        from ..settings import CONFIG_DIR, STATIC_DIR
    except Exception:
        return []
    out = []
    for d, label in ((CONFIG_DIR, "live config"), (STATIC_DIR, "reference table")):
        if d.is_dir():
            for p in sorted(d.iterdir()):
                if p.suffix in (".yml", ".yaml", ".csv") and p.stat().st_size < 200_000:
                    out.append((str(p), f"{label}: {p.name}"))
    return out


def index() -> Index:
    cfg = tuple(config_files())
    return _build(_stamp(), tuple((p, l) for p, l in cfg))


def search(query: str, scope: str = "all", k: int = 5) -> list[Chunk]:
    kinds = {"docs": ("doc",), "code": ("code",), "config": ("config",),
             "all": ("doc", "code", "config")}.get(scope, ("doc", "code", "config"))
    return [c for _, c in index().search(query, kinds, k)]


def chunk(chunk_id: str) -> Chunk | None:
    for c in index().chunks:
        if c.id == chunk_id:
            return c
    return None


def code_symbol(name: str) -> Chunk | None:
    """A function or class of the engine by name (the first that matches)."""
    name = str(name).strip().split(".")[-1].rstrip("()")
    for c in index().chunks:
        if c.kind == "code" and c.section == name:
            return c
    return None


def cite_label(c: Chunk) -> str:
    if c.kind == "doc":
        return f"{c.title} › {c.section} ({c.where})"
    if c.kind == "code":
        return f"{c.source}:{c.line} `{c.section}`"
    return c.title
