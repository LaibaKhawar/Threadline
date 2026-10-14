"""Password hashing, opaque session tokens and CSRF tokens."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

from app.core.config import get_settings

_hasher = PasswordHasher()

SESSION_COOKIE = "tl_session"
CSRF_COOKIE = "tl_csrf"
CSRF_HEADER = "x-csrf-token"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerificationError:
        return False
    except Exception:
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Sessions are stored hashed, so a database leak does not leak live session tokens."""
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_for_session(session_token: str) -> str:
    """CSRF token bound to the session (HMAC), checked against the header on unsafe methods."""
    key = get_settings().secret_key.encode()
    return hmac.new(key, ("csrf:" + session_token).encode(), hashlib.sha256).hexdigest()


def csrf_valid(session_token: str, header_value: str | None) -> bool:
    if not header_value:
        return False
    return hmac.compare_digest(csrf_for_session(session_token), header_value)
