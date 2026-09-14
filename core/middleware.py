"""HTTP middleware — extracted out of main.py (a composition root) so
request-handling logic lives in its own module instead of mixed into app
wiring. Registered on the app in main.py via app.middleware("http")(func);
registration order there must stay cors_middleware then
request_logging_middleware, matching the original @app.middleware decorator
order this was extracted from.
"""
import logging
import os
import time

from fastapi import Request

logger = logging.getLogger("ems")

# The frontend and API are served from the same Fly.io app (see
# routers/frontend.py's catch-all route), so a real browser session never
# needs cross-origin access at all — every prior "Access-Control-Allow-
# Origin: *" bought this app nothing for its own normal usage, only
# exposure: any other site could make authenticated requests using a
# token it obtained some other way (e.g. XSS). CORS_ALLOWED_ORIGINS lets
# an explicit allowlist opt back in (a future API consumer, an admin
# tool on a different origin) without reopening it to everyone.
ALLOWED_ORIGINS = {
    o.strip() for o in os.environ.get(
        "CORS_ALLOWED_ORIGINS", "https://ems-app.fly.dev,http://localhost:8000,http://127.0.0.1:8000"
    ).split(",") if o.strip()
}
CORS_ALLOWED_HEADERS = "Authorization, Content-Type, X-Institution-Id"


async def cors_middleware(request: Request, call_next):
    from fastapi.responses import Response
    origin = request.headers.get("origin")
    cors_headers = {
        "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": CORS_ALLOWED_HEADERS,
        "Access-Control-Max-Age": "86400",
    }
    if origin in ALLOWED_ORIGINS:
        cors_headers["Access-Control-Allow-Origin"] = origin
    if request.method == "OPTIONS":
        return Response(status_code=200, headers=cors_headers)
    response = await call_next(request)
    for k, v in cors_headers.items():
        response.headers[k] = v
    return response


async def request_logging_middleware(request: Request, call_next):
    """Logs every request (method, path, status, duration) and guarantees
    unhandled exceptions are logged with a stack trace before propagating —
    previously an unhandled error anywhere in an endpoint had no log trail
    at all beyond uvicorn's bare access line."""
    start = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        logger.exception("Unhandled error on %s %s (%sms)", request.method, request.url.path, duration_ms)
        raise
    duration_ms = round((time.monotonic() - start) * 1000, 1)
    level = logging.WARNING if response.status_code >= 500 else logging.INFO
    logger.log(level, "%s %s -> %s (%sms)", request.method, request.url.path, response.status_code, duration_ms)
    return response
