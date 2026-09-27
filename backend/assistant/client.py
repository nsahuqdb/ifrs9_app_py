"""The call to the model endpoint.

OpenAI-compatible chat completions, which is what every self-hosted gateway
speaks. The key goes in an Authorization header and nowhere else: the request
body is never logged, and the exception text carries the endpoint's own error
message rather than the payload that produced it.
"""
from __future__ import annotations

import requests

from .config import AssistantConfig


class AssistantError(RuntimeError):
    """A failure worth showing the user verbatim."""


def _trim(text: str, n: int = 300) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


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
        "messages": messages,
        "temperature": cfg.temperature,
        "top_p": cfg.top_p,
        "max_tokens": cfg.max_tokens,
    }
    try:
        resp = requests.post(cfg.endpoint, json=payload, headers=headers,
                             timeout=cfg.timeout_seconds, verify=cfg.verify_ssl)
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
        return body["choices"][0]["message"]["content"] or ""
    except Exception as exc:
        raise AssistantError(
            f"The model endpoint returned something unexpected: "
            f"{_trim(resp.text)}") from exc
