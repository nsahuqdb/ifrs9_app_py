"""Where the assistant's settings come from.

The endpoint, model and limits live in configuration. Several models can be
listed under ``assistant.models`` (Gemma 4, Gemma 3 ...); ``default_model``
names the one used unless the Assistant page picks another. A model's own
settings (endpoint, model name, key variable, certificate check, limits)
override the shared ones above it.

The API key never sits in a config file: it is read at call time from the
environment variable named in ``api_key_env``, or from the app folder's
``.env`` file (git-ignored), so a config file can be committed, copied into a
run's frozen snapshot and pasted into a ticket without carrying a credential.
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
    "key_required": False,
    "label": "",
}

APP_ROOT = Path(__file__).resolve().parents[2]


def _dotenv() -> dict[str, str]:
    """KEY=VALUE lines of the app folder's .env (read on every call, so an
    edited key works without a restart). Quotes around a value are dropped;
    lines starting with # are comments."""
    out: dict[str, str] = {}
    for p in (Path.cwd() / ".env", APP_ROOT / ".env"):
        if not p.is_file():
            continue
        try:
            for line in p.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip().removeprefix("export ").strip()
                v = v.strip().strip('"').strip("'")
                out.setdefault(k, v)
        except Exception:
            continue
    return out


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
    verify_ssl: bool | str = True        # True, False, or the path of a CA certificate file
    key_required: bool = False
    label: str = ""
    profile: str = ""                     # the entry of assistant.models in use
    source: str = "defaults"

    @property
    def api_key(self) -> str | None:
        """The key, read fresh from the environment on every call.

        Never stored on the object and never returned to a caller: the status
        endpoint reports only whether one is present.
        """
        v = os.environ.get(self.api_key_env, "").strip() or _dotenv().get(self.api_key_env, "").strip()
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
        if self.key_required and not self.api_key:
            return (f"{self.label or self.model} needs its API key: add the line "
                    f"{self.api_key_env}=<key> to {APP_ROOT / '.env'} (the key is read on every "
                    "question, no restart needed).")
        return None


def _config_paths() -> list[Path]:
    explicit = os.environ.get("IFRS9_APP_CONFIG", "").strip()
    out = [Path(explicit)] if explicit else []
    out += [Path.cwd() / "config.yml", Path(__file__).resolve().parents[2] / "config.yml"]
    return out


def _block() -> tuple[dict, str]:
    for p in _config_paths():
        if not p.is_file():
            continue
        try:
            block = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("assistant")
        except Exception:
            continue
        if isinstance(block, dict):
            return block, str(p)
    return {}, "defaults"


def list_models() -> list[dict]:
    """The models the config offers, for the Assistant page's picker: id,
    label, whether it is the default and whether it can be used now."""
    block, _ = _block()
    models = block.get("models") if isinstance(block.get("models"), dict) else {}
    default = str(os.environ.get("IFRS9_LLM_PROFILE") or block.get("default_model") or "")
    out = []
    for mid in models:
        cfg = load_config(mid)
        out.append({"id": mid, "label": cfg.label or cfg.model, "model": cfg.model,
                    "default": mid == default, "available": cfg.unavailable_reason() is None,
                    "reason": cfg.unavailable_reason(), "api_key_env": cfg.api_key_env})
    return out


def load_config(model: str | None = None) -> AssistantConfig:
    """Config file first, then the environment, then the defaults.

    ``model`` picks an entry of ``assistant.models``; without it the
    ``default_model`` is used (or IFRS9_LLM_PROFILE in the environment). The
    environment wins over the file, because a container is configured by
    environment and the file is what ships with the code.
    """
    values = dict(DEFAULTS)
    block, source = _block()
    values.update({k: v for k, v in block.items() if k in DEFAULTS})
    models = block.get("models") if isinstance(block.get("models"), dict) else {}
    chosen = str(model or os.environ.get("IFRS9_LLM_PROFILE") or block.get("default_model") or "")
    if chosen not in models and models and not model:
        chosen = next(iter(models))
    profile = ""
    if chosen in models and isinstance(models[chosen], dict):
        values.update({k: v for k, v in models[chosen].items() if k in DEFAULTS})
        profile = chosen

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
    values["key_required"] = bool(values["key_required"])
    v = values["verify_ssl"]
    if isinstance(v, str) and v.strip().lower() in ("true", "false", "yes", "no"):
        v = v.strip().lower() in ("true", "yes")
    values["verify_ssl"] = v if isinstance(v, (bool, str)) else bool(v)
    for k in ("temperature", "top_p", "timeout_seconds"):
        values[k] = float(values[k])
    for k in ("max_tokens", "max_history_turns", "max_context_chars",
              "max_tool_calls"):
        values[k] = int(values[k])
    values["label"] = str(values.get("label") or "")
    return AssistantConfig(**values, profile=profile, source=source)
