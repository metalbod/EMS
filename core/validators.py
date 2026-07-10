"""Shared Pydantic field validators used across multiple models/routers."""
MAX_LOGO_DATA_URL_LEN = 700_000  # ~500KB image after base64 overhead


def validate_logo_url(v):
    if v is None or v == "":
        return None
    if not v.startswith("data:image/"):
        raise ValueError("logo_url must be a data:image/... URI")
    if len(v) > MAX_LOGO_DATA_URL_LEN:
        raise ValueError("Logo image is too large (max ~500KB)")
    return v
