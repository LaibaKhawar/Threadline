"""Symmetric encryption for connector credentials (Fernet: AES-128-CBC + HMAC-SHA256)."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


def _fernet() -> Fernet:
    s = get_settings()
    key = s.encryption_key
    if not key:
        # Development fallback: derive a key from SECRET_KEY so local runs work without setup.
        # Production startup refuses an empty ENCRYPTION_KEY (see Settings validation).
        key = base64.urlsafe_b64encode(hashlib.sha256(("enc:" + s.secret_key).encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt_json(payload: dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps(payload).encode()).decode()


def decrypt_json(token: str) -> dict[str, Any]:
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except InvalidToken as exc:  # wrong key or tampered ciphertext
        raise ValueError("credential could not be decrypted") from exc
