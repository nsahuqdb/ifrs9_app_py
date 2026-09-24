from fastapi import APIRouter

from ifrs9qdb import __version__

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    """Liveness, and the engine version the container is running."""
    return {"status": "ok", "engine_version": __version__}
