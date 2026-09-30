from fastapi import APIRouter

from ifrs9qdb import __version__

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    """Liveness, the engine version the container is running, and who the
    app is acting as (IFRS9_USER, else the OS user) -- the default name on
    forms that record one."""
    from .. import settings
    return {"status": "ok", "engine_version": __version__,
            "user": settings.current_user()}
