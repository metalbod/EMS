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

import inspect
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
    sig = inspect.signature(func)
    params = list(sig.parameters.values())

    # Remove 'conn' parameter from the signature that FastAPI sees
    if params and params[0].name == 'conn':
        params = params[1:]

    new_sig = sig.replace(parameters=params)

    @wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        conn = get_db()
        try:
            return func(conn, *args, **kwargs)
        finally:
            conn.close()

    # Update wrapper's signature to exclude 'conn' so FastAPI doesn't try to inject it
    wrapper.__signature__ = new_sig
    return wrapper
