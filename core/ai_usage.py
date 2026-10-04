"""Token-usage recording for AI features (Settings -> AI Assistant -> Usage).

Called after a successful Anthropic call by routers/assistant.py (chat) and
routers/recruitment.py (resume extraction). Recording is best-effort: a
failure here is logged and swallowed, never allowed to fail the user's
actual chat reply or extraction."""
import logging
from typing import Optional

from db import get_db

logger = logging.getLogger("ems")

FEATURE_CHAT = "chat"
FEATURE_RESUME_EXTRACTION = "resume_extraction"


def tokens_from_response(resp) -> tuple:
    """(input_tokens, output_tokens) from an Anthropic response, 0/0 if the
    response carries no usage block."""
    usage = getattr(resp, "usage", None)
    return (
        int(getattr(usage, "input_tokens", 0) or 0),
        int(getattr(usage, "output_tokens", 0) or 0),
    )


def log_ai_usage(inst_id: int, user: dict, feature: str, model: str,
                 input_tokens: int, output_tokens: int) -> None:
    if not (input_tokens or output_tokens):
        return
    try:
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO ai_usage_log (institution_id,user_id,username,feature,model,input_tokens,output_tokens) "
                "VALUES (?,?,?,?,?,?,?)",
                (inst_id, user.get("id"), user.get("username"), feature, model, input_tokens, output_tokens),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.warning("failed to record AI usage (%s)", feature, exc_info=True)
