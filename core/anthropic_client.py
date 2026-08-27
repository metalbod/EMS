"""Anthropic API client resolution for the AI assistant chatbot
(routers/assistant.py).

An institution can supply its own Anthropic API key (BYOK — see
routers/assistant.py's settings endpoints, hr_manager-only) instead of
relying on the platform's own key. ANTHROPIC_API_KEY is now the platform
*default*, used for any institution that hasn't configured its own key —
it's optional, not fail-fast: an institution with neither its own key nor
a platform default just gets a "not configured" response (see
get_client_for_institution below) rather than the whole app refusing to
boot. This is a deliberate change from this module's earlier fail-fast
behavior — that used to break app boot (and every test that imports
main.py) in any environment without ANTHROPIC_API_KEY set, which is
exactly what happened to this project's own CI.
"""
import os

import anthropic

from core.secrets_encryption import decrypt_secret

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# Built once and reused for every institution using the platform default —
# building an anthropic.Anthropic() is cheap either way, but there's no
# reason to redo it every request for the common case. A BYOK institution's
# client is built fresh per call instead (see get_client_for_institution) —
# not worth caching per-institution given how infrequently the assistant is
# actually called (CHAT_RATE_LIMIT_PER_HOUR = 30/user/hour in
# routers/assistant.py) relative to the cost of a dict cache with no
# invalidation story for a rotated/removed key.
_platform_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None


def get_client_for_institution(conn, inst_id: int) -> "anthropic.Anthropic | None":
    """The Anthropic client to use for this institution's assistant
    requests: the institution's own BYOK key if it has one configured,
    else the platform default, else None (caller should treat that as
    "assistant not available for this institution")."""
    row = conn.execute(
        "SELECT anthropic_api_key_encrypted FROM institutions WHERE id=?", (inst_id,)
    ).fetchone()
    encrypted = row["anthropic_api_key_encrypted"] if row else None
    if encrypted:
        return anthropic.Anthropic(api_key=decrypt_secret(encrypted))
    return _platform_client
