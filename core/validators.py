"""Shared Pydantic field validators used across multiple models/routers."""
MAX_LOGO_DATA_URL_LEN = 700_000  # ~500KB image after base64 overhead
MAX_DOCUMENT_DATA_URL_LEN = 8_000_000  # ~6MB file after base64 overhead

DOCUMENT_MIME_PREFIXES = (
    "data:application/pdf",
    "data:application/msword",
    "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "data:text/plain",
    "data:image/",
)


def validate_logo_url(v):
    if v is None or v == "":
        return None
    if not v.startswith("data:image/"):
        raise ValueError("logo_url must be a data:image/... URI")
    if len(v) > MAX_LOGO_DATA_URL_LEN:
        raise ValueError("Logo image is too large (max ~500KB)")
    return v


def validate_document_data_url(v):
    if v is None or v == "":
        return None
    if not v.startswith(DOCUMENT_MIME_PREFIXES):
        raise ValueError("File must be a PDF, Word document, plain text, or image")
    if len(v) > MAX_DOCUMENT_DATA_URL_LEN:
        raise ValueError("File is too large (max ~6MB)")
    return v
