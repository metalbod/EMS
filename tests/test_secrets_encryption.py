"""Unit tests for core/secrets_encryption.py — the Fernet-based
encryption-at-rest helper backing the AI assistant's BYOK Anthropic key
(routers/assistant.py's settings endpoints). No DB/HTTP involved."""
import pytest

from core.secrets_encryption import encrypt_secret, decrypt_secret


def test_encrypt_decrypt_round_trip():
    plaintext = "sk-ant-api03-super-secret-value"
    ciphertext = encrypt_secret(plaintext)
    assert ciphertext != plaintext
    assert decrypt_secret(ciphertext) == plaintext


def test_ciphertext_does_not_contain_plaintext():
    plaintext = "sk-ant-api03-super-secret-value"
    ciphertext = encrypt_secret(plaintext)
    assert plaintext not in ciphertext


def test_decrypt_rejects_tampered_ciphertext():
    ciphertext = encrypt_secret("sk-ant-api03-super-secret-value")
    tampered = ciphertext[:-4] + ("A" if ciphertext[-4] != "A" else "B") + ciphertext[-3:]
    with pytest.raises(ValueError):
        decrypt_secret(tampered)


def test_decrypt_rejects_garbage_input():
    with pytest.raises(ValueError):
        decrypt_secret("not-a-real-fernet-token")


def test_encrypt_is_nondeterministic():
    # Fernet includes a random IV/timestamp per call, so encrypting the same
    # plaintext twice must not produce identical ciphertext.
    plaintext = "sk-ant-api03-super-secret-value"
    assert encrypt_secret(plaintext) != encrypt_secret(plaintext)
