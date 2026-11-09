from pathlib import Path

from fastapi import APIRouter

from ifrs9qdb import __version__

router = APIRouter(tags=["health"])


def _app_version() -> str:
    """The app version in pyproject.toml when this process started."""
    try:
        import tomllib
        p = Path(__file__).resolve().parents[2] / "pyproject.toml"
        return str(tomllib.loads(p.read_text(encoding="utf-8"))["project"]["version"])
    except Exception:                                    # noqa: BLE001
        return ""


# read once: a backend left running after a code update keeps reporting the
# version it started with, so the interface can say it needs a restart
APP_VERSION = _app_version()


@router.get("/health")
def health() -> dict:
    """Liveness, the engine version the container is running, the app
    version this process started with, and who the app is acting as
    (IFRS9_USER, else the OS user) -- the default name on forms that record
    one."""
    from .. import settings
    return {"status": "ok", "engine_version": __version__,
            "app_version": APP_VERSION, "user": settings.current_user()}
