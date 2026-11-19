"""Small cryptographic helpers: session tokens, HMAC-derived values and encryption
of provider tokens at rest."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet, InvalidToken


def new_session_token() -> str:
    """256 bits of randomness; only its SHA-256 hash is stored."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def derive(secret: bytes, purpose: str, value: str) -> str:
    """Keyed, purpose-separated digest (CSRF tokens, owner tags, rate-limit keys)."""
    return hmac.new(secret, f"{purpose}:{value}".encode(), hashlib.sha256).hexdigest()


def constant_time_equal(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and hmac.compare_digest(a.encode(), b.encode())


class TokenCipher:
    """Encrypts provider tokens before they are stored (Fernet: AES-128-CBC with
    HMAC-SHA256). A database leak alone does not reveal usable refresh tokens."""

    def __init__(self, key: bytes):
        self._f = Fernet(key)

    def encrypt(self, value: str) -> str:
        return self._f.encrypt(value.encode()).decode()

    def decrypt(self, value: str | None) -> str | None:
        if not value:
            return None
        try:
            return self._f.decrypt(value.encode()).decode()
        except InvalidToken:
            return None


def generate_fernet_key() -> str:
    return Fernet.generate_key().decode()
