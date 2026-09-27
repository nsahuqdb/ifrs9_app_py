"""Assistant endpoints.

The status endpoint exists so the page can say plainly why the feature is not
available, rather than offering a chat box that fails on the first question.
It never returns the API key, only whether one is present.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..assistant import TOOL_CATALOGUE, answer, load_config

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
        "tools": [line.split("(")[0] for line in TOOL_CATALOGUE.splitlines()],
    }


class Ask(BaseModel):
    question: str
    run_id: str | None = None
    history: list[dict] = Field(default_factory=list)


@router.post("/assistant/ask")
def ask(body: Ask) -> dict:
    if not body.question.strip():
        raise HTTPException(400, "ask a question")
    cfg = load_config()
    if cfg.unavailable_reason():
        raise HTTPException(503, cfg.unavailable_reason())
    # Only the two roles the protocol uses; anything else is not this app's.
    history = [m for m in body.history
               if m.get("role") in ("user", "assistant") and m.get("content")]
    return answer(body.question.strip(), history, body.run_id, cfg)
