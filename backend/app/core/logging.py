"""Structured JSON logging with secret redaction and request-scoped context."""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any

import structlog

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)

SENSITIVE_KEYS = {
    "password", "password_hash", "token", "access_token", "refresh_token", "api_key", "secret",
    "client_secret", "authorization", "cookie", "session", "credentials", "encryption_key",
    "secret_key", "body", "content", "text",
}
_TOKEN_PATTERNS = [
    re.compile(r"(?i)bearer\s+[a-z0-9._\-]+"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bya29\.[A-Za-z0-9_\-]+"),
]


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        for pat in _TOKEN_PATTERNS:
            value = pat.sub("[REDACTED]", value)
        return value
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if k.lower() in SENSITIVE_KEYS else redact_value(v)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact_value(v) for v in value]
    return value


def _redact_processor(_logger: Any, _name: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    return {
        k: ("[REDACTED]" if k.lower() in SENSITIVE_KEYS else redact_value(v)) for k, v in event_dict.items()
    }


def _context_processor(_logger: Any, _name: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    rid, uid = request_id_var.get(), user_id_var.get()
    if rid:
        event_dict.setdefault("request_id", rid)
    if uid:
        event_dict.setdefault("user_id", uid)
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _context_processor,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact_processor,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "threadline") -> Any:
    return structlog.get_logger(name)
