import json

import pytest

from app.core.crypto import decrypt_json, encrypt_json
from app.core.logging import redact_value
from app.core.security import csrf_for_session, csrf_valid, hash_password, hash_token, verify_password


def test_credentials_roundtrip_and_tamper_detection() -> None:
    token = encrypt_json({"access_token": "ya29.secret", "refresh_token": "r"})
    assert "ya29" not in token
    assert decrypt_json(token)["refresh_token"] == "r"
    with pytest.raises(ValueError):
        decrypt_json(token[:-4] + "AAAA")


def test_password_hashing_and_session_tokens() -> None:
    h = hash_password("correct horse")
    assert verify_password(h, "correct horse") and not verify_password(h, "wrong")
    assert hash_token("abc") != "abc" and len(hash_token("abc")) == 64


def test_csrf_bound_to_session() -> None:
    t = csrf_for_session("session-a")
    assert csrf_valid("session-a", t)
    assert not csrf_valid("session-b", t) and not csrf_valid("session-a", None)


def test_log_redaction() -> None:
    red = redact_value({"password": "x", "nested": {"api_key": "sk-abcdefghijklmnopqrstu", "note": "Bearer abc.def"}, "ok": 1})
    s = json.dumps(red)
    assert "sk-abc" not in s and "abc.def" not in s and red["ok"] == 1 and red["password"] == "[REDACTED]"


def test_production_config_requires_secrets() -> None:
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(environment="production", secret_key="dev-only-secret", encryption_key="", cookie_secure=True)
    with pytest.raises(ValidationError):
        Settings(embedding_dim=768)
