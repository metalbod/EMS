"""Encryption at rest for tenant-supplied third-party credentials — e.g. an
institution's own Anthropic API key for the AI assistant (BYOK, see
routers/assistant.py's settings endpoints). Generic on purpose (named for
"tenant secrets", not "Anthropic keys") in case another BYOK-style
credential needs the same treatment later.

bcrypt (used elsewhere in this codebase for passwords and device API keys —
see core/deps.py) is one-way and useless here: those never need to be
recovered, only verified, but a tenant's Anthropic key has to be sent back
to Anthropic in plaintext on every chat request, so it needs genuine
reversible encryption, not a hash.

TENANT_SECRETS_ENCRYPTION_KEY fail-fast check, same pattern as JWT_SECRET
in core/deps.py: a random key is deliberately NOT generated as a fallback —
that would silently make every previously-encrypted secret undecryptable
on the next restart. Accepts any long random string (not required to be a
pre-formatted Fernet key) — SHA-256 the configured secret into Fernet's
required 32-byte urlsafe-base64 key so setup is "set one long random
string", matching JWT_SECRET's own setup instructions exactly, not a
separate "run this key-generation command" step.

Single-key model: there is no key-rotation/versioning support yet. If that
becomes necessary, the straightforward upgrade is prefixing ciphertext
with a key-version tag and trying each known key in turn on decrypt — not
built now since nothing needs it yet.
"""
import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

TENANT_SECRETS_ENCRYPTION_KEY = os.environ.get("TENANT_SECRETS_ENCRYPTION_KEY")
if not TENANT_SECRETS_ENCRYPTION_KEY:
    raise RuntimeError(
        "TENANT_SECRETS_ENCRYPTION_KEY environment variable is not set. A random key is "
        "deliberately NOT generated as a fallback — that would silently make every "
        "previously-encrypted tenant secret (e.g. an institution's own Anthropic API key) "
        "undecryptable on the next restart, and break decryption entirely across multiple "
        "worker processes/machines (each would derive a different key). Set "
        "TENANT_SECRETS_ENCRYPTION_KEY explicitly to a long random string (see .env.example)."
    )

_fernet_key = base64.urlsafe_b64encode(hashlib.sha256(TENANT_SECRETS_ENCRYPTION_KEY.encode()).digest())
_fernet = Fernet(_fernet_key)


def encrypt_secret(plaintext: str) -> str:
    """Encrypts a plaintext credential for storage. Returns an opaque
    ciphertext string safe to store in a TEXT column."""
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    """Decrypts a value previously returned by encrypt_secret(). Raises
    ValueError if the ciphertext is malformed or was encrypted under a
    different TENANT_SECRETS_ENCRYPTION_KEY (e.g. the key was rotated
    without re-encrypting existing rows) — callers should treat that as
    "this stored credential is no longer usable", not crash the caller."""
    try:
        return _fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        raise ValueError("Stored secret could not be decrypted — it may have been encrypted under a different key")
