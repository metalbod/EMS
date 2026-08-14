"""Anthropic API client singleton for the AI assistant chatbot
(routers/assistant.py). Fail-fast at import time, mirroring core/deps.py's
JWT_SECRET check — a missing key should break app boot loudly, not surface
as a mysterious 500 on the first chat message.
"""
import os

import anthropic

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    raise RuntimeError(
        "ANTHROPIC_API_KEY environment variable is not set. Required for the "
        "AI assistant chatbot (routers/assistant.py). Set it via `fly secrets "
        "set ANTHROPIC_API_KEY=...` in production or .env locally."
    )

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
