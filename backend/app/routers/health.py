"""
Health check router.
"""
from fastapi import APIRouter
from sqlalchemy import text

from app.database import SessionLocal

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check() -> dict:
    """
    Returns API health status, database connectivity, and playwright status.
    Always returns HTTP 200 so load balancers can distinguish app vs. infra issues.
    """
    db_status = "connected"
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
    except Exception as exc:
        db_status = f"error: {exc}"

    playwright_available = False
    try:
        import playwright  # noqa: F401
        playwright_available = True
    except ImportError:
        playwright_available = False

    return {
        "status": "ok",
        "version": "1.0.0",
        "db": db_status,
        "playwright_available": playwright_available,
    }

