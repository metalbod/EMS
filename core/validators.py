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

# Public job-application resume uploads (routers/public_careers.py) use a
# tighter allowlist than HR's own candidate_documents upload — the only
# truly public, unauthenticated upload surface in this app, and resumes are
# never plain text or images in practice, so dropping those two shrinks
# what an anonymous visitor can get stored and served back out again.
PUBLIC_RESUME_MIME_PREFIXES = (
    "data:application/pdf",
    "data:application/msword",
    "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document",
)

# AI resume-extraction upload (routers/recruitment.py's extract_resume_fields)
# — narrower still than either allowlist above, not for privacy/abuse
# reasons like the public one, but because Anthropic's API only natively
# accepts PDF and image as a document/vision content block. Word (.doc/
# .docx) is still accepted by the *regular* candidate_documents upload (see
# DOCUMENT_MIME_PREFIXES) — HR can still attach a Word resume as a file,
# there's just no AI-extract button for it (see static/js/recruitment.js's
# own file-type gate on that button) rather than silently failing a real
# upload or adding a server-side Word→PDF conversion step.
AI_EXTRACTABLE_MIME_PREFIXES = (
    "data:application/pdf",
    "data:image/jpeg",
    "data:image/png",
    "data:image/gif",
    "data:image/webp",
)


def validate_ai_extractable_data_url(v):
    if v is None or v == "":
        return None
    if not v.startswith(AI_EXTRACTABLE_MIME_PREFIXES):
        raise ValueError("AI extraction only supports PDF or image (JPEG/PNG/GIF/WebP) files")
    if len(v) > MAX_DOCUMENT_DATA_URL_LEN:
        raise ValueError("File is too large (max ~6MB)")
    return v


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


def validate_public_resume_data_url(v):
    if v is None or v == "":
        return None
    if not v.startswith(PUBLIC_RESUME_MIME_PREFIXES):
        raise ValueError("Resume must be a PDF or Word document")
    if len(v) > MAX_DOCUMENT_DATA_URL_LEN:
        raise ValueError("File is too large (max ~6MB)")
    return v
