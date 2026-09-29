"""Where everything lives, in one place.

The layout is the R app's, so the two apps can share a project folder:

    <project>/
      config.yml                  run settings: paths, on_validation_error,
                                  approval (separation of duties), uploads
      config/                     model.yml, model_inputs.yml, overlays.yml,
                                  validation_suppressions.yml,
                                  calculator_versions.yml
      data-raw/static/            the static reference tables
      config_snapshots/           frozen, versioned copies of the two above
      runs/                       one folder per run
      logs/etl_audit.jsonl        the project audit log
      input/                      the configured input directory

Every path can be overridden from the environment -- IFRS9_PROJECT_ROOT for
the lot, or IFRS9_RUNS_DIR, IFRS9_CONFIG_DIR, IFRS9_STATIC_DIR, IFRS9_CONFIG,
IFRS9_SNAPSHOTS_DIR, IFRS9_INPUT_DIR, IFRS9_DATA_DROP_ROOT, IFRS9_UPLOAD_DIR,
IFRS9_AUDIT_LOG and IFRS9_OVERLAYS one at a time. Where the project has no
config/ or static/ of its own, the engine package's copies are used, so a
fresh checkout runs.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

APP_ROOT = Path(__file__).resolve().parent.parent


def _env_path(name: str, default) -> Path:
    v = os.environ.get(name)
    return Path(v).expanduser() if v else Path(default)


PROJECT_ROOT = _env_path("IFRS9_PROJECT_ROOT", APP_ROOT)
PROJECT_CONFIG = _env_path("IFRS9_CONFIG", PROJECT_ROOT / "config.yml")
CONFIG_DIR = _env_path("IFRS9_CONFIG_DIR", PROJECT_ROOT / "config")
STATIC_DIR = _env_path("IFRS9_STATIC_DIR", PROJECT_ROOT / "data-raw" / "static")
RUNS_DIR = _env_path("IFRS9_RUNS_DIR", PROJECT_ROOT / "runs")
SNAPSHOTS_ROOT = _env_path("IFRS9_SNAPSHOTS_DIR", PROJECT_ROOT / "config_snapshots")
UPLOAD_DIR = _env_path("IFRS9_UPLOAD_DIR", PROJECT_ROOT / "uploads")
AUDIT_LOG = _env_path("IFRS9_AUDIT_LOG", PROJECT_ROOT / "logs" / "etl_audit.jsonl")
OVERLAYS_FILE = _env_path("IFRS9_OVERLAYS", CONFIG_DIR / "overlays.yml")
SUPPRESSIONS_FILE = CONFIG_DIR / "validation_suppressions.yml"


def ensure_project() -> list[str]:
    """Seed a project folder that has no config of its own from the app's.

    A deployment puts the project on a mounted volume (IFRS9_PROJECT_ROOT), so
    that config edits, versions, runs and the audit log survive a redeploy.
    The first start copies the shipped config.yml, config/ and data-raw/static/
    there; after that the volume's copies are the live ones and are never
    overwritten.
    """
    import shutil
    seeded = []
    if PROJECT_ROOT.resolve() == APP_ROOT.resolve():
        return seeded
    PROJECT_ROOT.mkdir(parents=True, exist_ok=True)
    for rel in ("config.yml", "config", "data-raw"):
        src, dst = APP_ROOT / rel, PROJECT_ROOT / rel
        if dst.exists() or not src.exists():
            continue
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        seeded.append(rel)
    return seeded


def run_config() -> dict:
    """config.yml, or {} when there is none."""
    if PROJECT_CONFIG.is_file():
        try:
            return yaml.safe_load(PROJECT_CONFIG.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
    return {}


def _resolve(p) -> Path | None:
    if not p:
        return None
    p = Path(str(p)).expanduser()
    return p if p.is_absolute() else PROJECT_ROOT / p


def input_dir() -> Path:
    """The configured input directory: env, then config.yml, then input/."""
    env = os.environ.get("IFRS9_INPUT_DIR")
    if env:
        return Path(env).expanduser()
    p = _resolve((run_config().get("paths") or {}).get("input_dir"))
    return p or PROJECT_ROOT / "input"


def data_drop_root() -> Path | None:
    env = os.environ.get("IFRS9_DATA_DROP_ROOT")
    if env:
        return Path(env).expanduser()
    return _resolve((run_config().get("paths") or {}).get("data_drop_root"))


def on_validation_error() -> str:
    v = str((run_config().get("run") or {}).get("on_validation_error") or "warn")
    return v if v in ("stop", "warn", "ignore") else "warn"


def max_upload_mb() -> int:
    try:
        v = int((run_config().get("run") or {}).get("max_upload_size_mb") or 500)
        return v if v > 0 else 500
    except (TypeError, ValueError):
        return 500


def config_dir_for_run() -> Path | None:
    """The live config/ a run reads, or None for the engine's own."""
    return CONFIG_DIR if (CONFIG_DIR / "model.yml").is_file() else None


def static_dir_for_run() -> Path | None:
    """The live static reference a run reads, or None for the engine's own."""
    return STATIC_DIR if STATIC_DIR.is_dir() and any(STATIC_DIR.glob("*.csv")) \
        else None


def current_user() -> str:
    """Who is acting. The app has no login of its own (the R app reads the OS
    user), so IFRS9_USER names the deployment's user and a request can name
    itself where the page asks."""
    u = os.environ.get("IFRS9_USER") or os.environ.get("USER") \
        or os.environ.get("USERNAME")
    if u:
        return u
    try:
        import getpass
        return getpass.getuser()
    except Exception:
        return "unknown"


def separation_enforced() -> bool:
    return bool((run_config().get("approval") or {})
                .get("enforce_separation_of_duties"))
