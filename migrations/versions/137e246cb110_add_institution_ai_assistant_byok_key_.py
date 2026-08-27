"""add institution ai assistant byok key columns

Revision ID: 137e246cb110
Revises: 4a9d885ac5f5
Create Date: 2026-08-27 16:55:20.396340

An institution can now supply its own Anthropic API key for the AI
assistant chatbot (routers/assistant.py's settings endpoints) instead of
relying on the platform's own ANTHROPIC_API_KEY. anthropic_api_key_encrypted
is Fernet ciphertext (core/secrets_encryption.py) — the plaintext key is
never stored. anthropic_api_key_last4 is a plain (unencrypted) copy of just
the last 4 characters, kept only so the settings page can render "key
ending in ...XXXX" without decrypting on every page load.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '137e246cb110'
down_revision: Union[str, Sequence[str], None] = '4a9d885ac5f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE institutions ADD COLUMN IF NOT EXISTS anthropic_api_key_encrypted TEXT")
    op.execute("ALTER TABLE institutions ADD COLUMN IF NOT EXISTS anthropic_api_key_last4 TEXT")
    op.execute("ALTER TABLE institutions ADD COLUMN IF NOT EXISTS anthropic_api_key_added_at TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE institutions DROP COLUMN IF EXISTS anthropic_api_key_added_at")
    op.execute("ALTER TABLE institutions DROP COLUMN IF EXISTS anthropic_api_key_last4")
    op.execute("ALTER TABLE institutions DROP COLUMN IF EXISTS anthropic_api_key_encrypted")
