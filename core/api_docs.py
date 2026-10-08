"""Whether the app serves its own interactive API docs (Swagger UI, ReDoc) and
raw OpenAPI schema.

Off unless ENABLE_API_DOCS is set to a truthy value — that way production
(where the variable is simply never set) exposes none of it, and nothing has
to remember to turn it off on a new deployment. Local dev opts in via .env.
The schema lists every endpoint, parameter and request field to anyone who
can reach the URL, with no login required; the endpoints themselves still
need a token, so this is about not handing outsiders a map, not about
protecting data."""

_TRUTHY = {"1", "true", "yes", "on"}


def api_docs_urls(environ) -> dict:
    """FastAPI() keyword arguments: the three doc URLs, or None for each when disabled."""
    enabled = str(environ.get("ENABLE_API_DOCS", "")).strip().lower() in _TRUTHY
    return {
        "docs_url": "/api/docs" if enabled else None,
        "redoc_url": "/api/redoc" if enabled else None,
        "openapi_url": "/api/openapi.json" if enabled else None,
    }
