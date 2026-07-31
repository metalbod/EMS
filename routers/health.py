"""Liveness/readiness probe for Fly.io — extracted out of main.py (a
composition root) so the health check lives alongside every other route
instead of being the one endpoint still defined inline."""
from fastapi import APIRouter, HTTPException

try:
    from db import get_db
except ImportError:
    from ems.db import get_db

try:
    from core.schemas import HealthResponse
except ImportError:
    from ems.core.schemas import HealthResponse

router = APIRouter()


@router.api_route("/health", methods=["GET", "HEAD"], response_model=HealthResponse, tags=["health"])
def health():
    """Confirms the process is up and the DB pool can serve a connection.

    Supports both GET (returns JSON) and HEAD (returns status code only) for
    monitoring services. HEAD requests are used by UptimeRobot free plan and
    other lightweight health checks.
    """
    try:
        conn = get_db()
        conn.execute("SELECT 1")
        conn.close()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(503, f"unhealthy: {e}")
