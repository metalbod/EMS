"""Database session management via decorator.

Provides @db_session decorator to auto-close connections, eliminating
manual try/finally patterns and reducing connection pool exhaustion risk.

Usage:
    @router.get("/api/endpoint")
    @db_session
    def my_endpoint(conn, user: dict = Depends(require_roles(...))):
        rows = conn.execute("SELECT * FROM table").fetchall()
        return [dict(r) for r in rows]
        # conn.close() happens automatically

The decorator:
- Injects conn as first parameter after user/request context
- Guarantees conn.close() even if function raises exception
- Preserves function signature and FastAPI dependency injection
"""

from functools import wraps
from typing import Callable, Any

try:
    from db import get_db
except ImportError:
    from ems.db import get_db


def db_session(func: Callable) -> Callable:
    """Decorator to auto-manage database connections.

    Injects a database connection as the first parameter and guarantees
    it's closed after the function completes, even on exception.

    The decorated function should have conn as its first parameter:
        def my_endpoint(conn, user: dict = Depends(...)):
            ...

    FastAPI will handle dependency injection for other parameters normally.
    """

    @wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        conn = get_db()
        try:
            # Inject connection as first positional argument
            return func(conn, *args, **kwargs)
        finally:
            # Guarantee cleanup even on exception
            conn.close()

    return wrapper
