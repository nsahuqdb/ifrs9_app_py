"""Assistant endpoints.

The status endpoint exists so the page can say plainly why the feature is not
available, rather than offering a chat box that fails on the first question.
It never returns the API key, only whether one is present.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..assistant import TOOLS, answer, load_config
from ..assistant.config import list_models
from ..assistant.agent import RAW

router = APIRouter(tags=["assistant"])


@router.get("/assistant/status")
def status() -> dict:
    cfg = load_config()
    return {
        "available": cfg.unavailable_reason() is None,
        "reason": cfg.unavailable_reason(),
        "model": cfg.model or None,
        "endpoint_configured": bool(cfg.endpoint),
        "api_key_present": cfg.api_key is not None,
        "api_key_env": cfg.api_key_env,
        "max_tool_calls": cfg.max_tool_calls,
        "config_source": cfg.source,
        "tools": list(TOOLS) + list(RAW),
        "profile": cfg.profile,
        "label": cfg.label or cfg.model,
        "models": list_models(),
    }


@router.get("/regulatory/file/{path:path}")
def regulatory_file(path: str):
    """A regulatory text from docs/regulatory, shown in the browser (a PDF
    opens at the page the link names). Only files inside that folder."""
    from fastapi.responses import FileResponse
    from ..assistant.regulatory import READABLE, REG_DIR
    root = REG_DIR.resolve()
    p = (root / path).resolve()
    if root not in p.parents or not p.is_file() or p.suffix.lower() not in READABLE:
        raise HTTPException(404, "No such regulatory document.")
    media = {".pdf": "application/pdf", ".md": "text/plain; charset=utf-8",
             ".txt": "text/plain; charset=utf-8", ".htm": "text/html", ".html": "text/html",
             ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    disp = "attachment" if p.suffix.lower() == ".docx" else "inline"
    from urllib.parse import quote
    return FileResponse(p, media_type=media.get(p.suffix.lower()),
                        headers={"Content-Disposition": f"{disp}; filename*=UTF-8''{quote(p.name)}"})


class Ask(BaseModel):
    question: str
    run_id: str | None = None
    history: list[dict] = Field(default_factory=list)
    model: str | None = None        # an entry of assistant.models; None = the default


@router.post("/assistant/ask")
def ask(body: Ask) -> dict:
    if not body.question.strip():
        raise HTTPException(400, "ask a question")
    cfg = load_config(body.model or None)
    if cfg.unavailable_reason():
        raise HTTPException(503, cfg.unavailable_reason())
    # Only the two roles the protocol uses; anything else is not this app's.
    history = [m for m in body.history
               if m.get("role") in ("user", "assistant") and m.get("content")]
    return answer(body.question.strip(), history, body.run_id, cfg)
