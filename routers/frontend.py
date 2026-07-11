"""SPA frontend catch-all route. Must be mounted last (after every API router)
since it matches any path not already claimed by a more specific route."""
import hashlib
import os
import re

from fastapi import APIRouter
from fastapi.responses import Response

router = APIRouter()

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")

_CACHE_BUST_RE = re.compile(r"\?v=[A-Za-z0-9]+")
_index_html_cache = {"version": None, "content": None}


def _static_asset_version() -> str:
    """Cache-busting token derived from every file under static/ — changes
    automatically whenever any static asset's content changes. Replaces the
    previous scheme of manually editing '?v=N' across ~19 references in
    index.html by hand on every frontend change (error-prone: miss one file
    and a stale asset gets served after deploy)."""
    h = hashlib.md5()
    for root, _, files in os.walk(STATIC_DIR):
        for name in sorted(files):
            path = os.path.join(root, name)
            h.update(path.encode())
            h.update(str(os.path.getmtime(path)).encode())
    return h.hexdigest()[:10]


@router.get("/{full_path:path}")
def serve_frontend(full_path: str):
    version = _static_asset_version()
    if _index_html_cache["version"] != version:
        with open(os.path.join(STATIC_DIR, "index.html"), "r", encoding="utf-8") as f:
            raw = f.read()
        _index_html_cache["content"] = _CACHE_BUST_RE.sub(f"?v={version}", raw)
        _index_html_cache["version"] = version
    return Response(content=_index_html_cache["content"], media_type="text/html")
