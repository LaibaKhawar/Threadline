"""Domain errors mapped to HTTP responses without leaking internals."""

from __future__ import annotations


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class PrivacyViolation(AppError):
    """Raised when an operation would send data somewhere the privacy policy forbids."""

    status_code = 403
    code = "privacy_policy"


class ApprovalRequired(AppError):
    status_code = 409
    code = "approval_required"
