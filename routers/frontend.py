"""SPA frontend catch-all route. Must be mounted last (after every API router)
since it matches any path not already claimed by a more specific route."""
import hashlib
import os
import re

from fastapi import APIRouter
from fastapi.responses import Response
from starlette.staticfiles import StaticFiles

router = APIRouter()

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")

_CACHE_BUST_RE = re.compile(r"\?v=[A-Za-z0-9]+")
_index_html_cache = {"version": None, "content": None}
_version_cache = {"value": None}


def _static_asset_version() -> str:
    """Cache-busting token derived from every file under static/ — changes
    automatically whenever any static asset's content changes. Replaces the
    previous scheme of manually editing '?v=N' across ~19 references in
    index.html by hand on every frontend change (error-prone: miss one file
    and a stale asset gets served after deploy).

    Computed once per process and cached (module-level _version_cache)
    rather than on every request: static files never change during a
    running process's lifetime — a deployed container is immutable, and
    local dev's uvicorn runs without --reload (see CLAUDE.md), so a file
    change there needs a manual restart either way. Walking every file
    under static/ and stat-ing each one on every single non-API request
    (any page nav, any hard refresh) bought nothing and only got slower as
    more static assets were added."""
    if _version_cache["value"] is None:
        h = hashlib.md5()
        for root, _, files in os.walk(STATIC_DIR):
            for name in sorted(files):
                path = os.path.join(root, name)
                h.update(path.encode())
                h.update(str(os.path.getmtime(path)).encode())
        _version_cache["value"] = h.hexdigest()[:10]
    return _version_cache["value"]


class CachedStaticFiles(StaticFiles):
    """Long-lived, immutable Cache-Control on every /static/* response.
    Safe because every reference to these files in index.html already
    carries the content-hash query string above (?v=<hash>) — a changed
    file is always requested under a brand-new URL, so the browser never
    needs to re-check an old one; it can just keep it forever. index.html
    itself is NOT served through this class (see serve_frontend below,
    a separate route) so it's always fetched fresh and can reference the
    current hash."""
    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


@router.get("/{full_path:path}")
def serve_frontend(full_path: str):
    version = _static_asset_version()
    if _index_html_cache["version"] != version:
        with open(os.path.join(STATIC_DIR, "index.html"), "r", encoding="utf-8") as f:
            raw = f.read()
        _index_html_cache["content"] = _CACHE_BUST_RE.sub(f"?v={version}", raw)
        _index_html_cache["version"] = version
    return Response(content=_index_html_cache["content"], media_type="text/html")
