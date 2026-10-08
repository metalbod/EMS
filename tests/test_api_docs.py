"""core/api_docs.py: interactive API docs and the OpenAPI schema are opt-in."""
import pytest

from core.api_docs import api_docs_urls

OFF = {"docs_url": None, "redoc_url": None, "openapi_url": None}


@pytest.mark.parametrize("env", [{}, {"ENABLE_API_DOCS": ""}, {"ENABLE_API_DOCS": "false"}, {"ENABLE_API_DOCS": "0"}])
def test_docs_disabled_unless_explicitly_enabled(env):
    assert api_docs_urls(env) == OFF


@pytest.mark.parametrize("value", ["true", "TRUE", "1", " yes "])
def test_docs_enabled_by_flag(value):
    assert api_docs_urls({"ENABLE_API_DOCS": value}) == {
        "docs_url": "/api/docs", "redoc_url": "/api/redoc", "openapi_url": "/api/openapi.json",
    }
