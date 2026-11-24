"""The call to the model endpoint.

OpenAI-compatible chat completions, which is what every self-hosted gateway
speaks. The key goes in an Authorization header and nowhere else: the request
body is never logged, and the exception text carries the endpoint's own error
message rather than the payload that produced it.
"""
from __future__ import annotations

import re
import warnings

import requests

from .config import AssistantConfig

# Reasoning models may put their working before the answer; only the answer
# is the reply.
_THINK = re.compile(r"<(think|thinking|thought|reasoning)>.*?</\1>", re.S | re.I)


def _verify(cfg: AssistantConfig):
    """requests' verify: True, False, or a CA certificate file. With the check
    off (an internal gateway whose certificate Python does not trust), the
    warning urllib3 prints on every call is silenced for that call only."""
    v = cfg.verify_ssl
    if isinstance(v, str) and v.strip():
        return v.strip()
    return bool(v)


class AssistantError(RuntimeError):
    """A failure worth showing the user verbatim."""


def _trim(text: str, n: int = 300) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def alternate(messages: list[dict]) -> list[dict]:
    """The conversation as strict-template models (Gemma, Mistral, Llama 2
    on vLLM) accept it: at most one system message first, then user and
    assistant taking turns, starting and ending with the user. Messages of
    the same role in a row are joined into one; nothing is dropped."""
    system = "\n\n".join(str(m.get("content") or "") for m in messages
                         if m.get("role") == "system").strip()
    turns: list[dict] = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            continue
        role = "assistant" if role == "assistant" else "user"
        text = str(m.get("content") or "")
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] += "\n\n" + text
        else:
            turns.append({"role": role, "content": text})
    if not turns or turns[0]["role"] != "user":
        turns.insert(0, {"role": "user", "content": "(conversation start)"})
    if turns[-1]["role"] != "user":
        turns.append({"role": "user", "content": "Continue."})
    return ([{"role": "system", "content": system}] if system else []) + turns


def chat(messages: list[dict], cfg: AssistantConfig) -> str:
    """One round trip. Returns the assistant's message content."""
    reason = cfg.unavailable_reason()
    if reason:
        raise AssistantError(reason)

    headers = {"Content-Type": "application/json"}
    key = cfg.api_key
    if key:
        headers["Authorization"] = f"Bearer {key}"

    payload = {
        "model": cfg.model,
        "messages": alternate(messages),
        "temperature": cfg.temperature,
        "top_p": cfg.top_p,
        "max_tokens": cfg.max_tokens,
    }
    try:
        verify = _verify(cfg)
        with warnings.catch_warnings():
            if verify is False:
                from urllib3.exceptions import InsecureRequestWarning
                warnings.simplefilter("ignore", InsecureRequestWarning)
            resp = requests.post(cfg.endpoint, json=payload, headers=headers,
                                 timeout=cfg.timeout_seconds, verify=verify)
    except requests.Timeout as exc:
        raise AssistantError(
            f"The model did not answer within {cfg.timeout_seconds:g}s.") from exc
    except requests.RequestException as exc:
        # The endpoint, not the payload: the payload may hold run data.
        raise AssistantError(
            f"Could not reach the model endpoint: {_trim(exc, 200)}") from exc

    if resp.status_code >= 400:
        raise AssistantError(
            f"The model endpoint returned HTTP {resp.status_code}: "
            f"{_trim(resp.text)}")
    try:
        body = resp.json()
        msg = body["choices"][0]["message"]
        return _THINK.sub("", msg.get("content") or "").strip()
    except Exception as exc:
        raise AssistantError(
            f"The model endpoint returned something unexpected: "
            f"{_trim(resp.text)}") from exc
