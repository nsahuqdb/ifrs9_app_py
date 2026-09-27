"""Where the assistant's settings come from.

The endpoint, model and limits live in configuration. The API key never does:
it is read at call time from the environment variable named in ``api_key_env``,
so a config file can be committed, copied into a run's frozen snapshot and
pasted into a ticket without carrying a credential.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULTS = {
    "enabled": True,
    "endpoint": "",
    "model": "",
    "temperature": 0.3,
    "top_p": 0.8,
    "max_tokens": 1024,
    "timeout_seconds": 60,
    "api_key_env": "IFRS9_LLM_API_KEY",
    "max_history_turns": 8,
    "max_context_chars": 24000,
    "max_tool_calls": 6,
    "verify_ssl": True,
}


@dataclass
class AssistantConfig:
    enabled: bool = True
    endpoint: str = ""
    model: str = ""
    temperature: float = 0.3
    top_p: float = 0.8
    max_tokens: int = 1024
    timeout_seconds: float = 60
    api_key_env: str = "IFRS9_LLM_API_KEY"
    max_history_turns: int = 8
    max_context_chars: int = 24000
    max_tool_calls: int = 6
    verify_ssl: bool = True
    source: str = "defaults"

    @property
    def api_key(self) -> str | None:
        """The key, read fresh from the environment on every call.

        Never stored on the object and never returned to a caller: the status
        endpoint reports only whether one is present.
        """
        v = os.environ.get(self.api_key_env, "").strip()
        return v or None

    def unavailable_reason(self) -> str | None:
        """Why the assistant cannot answer, in a sentence a user can act on."""
        if not self.enabled:
            return "The assistant is switched off in this deployment's config."
        if not self.endpoint:
            return ("No LLM endpoint is configured. Set assistant.endpoint in "
                    "the app config, or IFRS9_LLM_ENDPOINT in the environment.")
        if not self.model:
            return ("No model is configured. Set assistant.model in the app "
                    "config, or IFRS9_LLM_MODEL in the environment.")
        return None


def _config_paths() -> list[Path]:
    explicit = os.environ.get("IFRS9_APP_CONFIG", "").strip()
    out = [Path(explicit)] if explicit else []
    out += [Path.cwd() / "config.yml", Path(__file__).resolve().parents[2] / "config.yml"]
    return out


def load_config() -> AssistantConfig:
    """Config file first, then the environment, then the defaults.

    The environment wins over the file, because a container is configured by
    environment and the file is what ships with the code.
    """
    values = dict(DEFAULTS)
    source = "defaults"
    for p in _config_paths():
        if not p.is_file():
            continue
        try:
            block = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("assistant")
        except Exception:
            continue
        if isinstance(block, dict):
            values.update({k: v for k, v in block.items() if k in DEFAULTS})
            source = str(p)
            break

    env = {
        "endpoint": os.environ.get("IFRS9_LLM_ENDPOINT"),
        "model": os.environ.get("IFRS9_LLM_MODEL"),
        "api_key_env": os.environ.get("IFRS9_LLM_API_KEY_ENV"),
    }
    from_env = False
    for k, v in env.items():
        if v:
            values[k] = v
            from_env = True
    if from_env:
        source = "environment" if source == "defaults" else f"{source} + environment"

    values["enabled"] = bool(values["enabled"])
    for k in ("temperature", "top_p", "timeout_seconds"):
        values[k] = float(values[k])
    for k in ("max_tokens", "max_history_turns", "max_context_chars",
              "max_tool_calls"):
        values[k] = int(values[k])
    return AssistantConfig(**values, source=source)
