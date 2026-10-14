"""Upload validation: extension allow-list, magic-byte check, size limit, safe stored names."""

from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
from dataclasses import dataclass
from pathlib import Path

ALLOWED: dict[str, tuple[str, ...]] = {
    # extension -> acceptable MIME types
    ".pdf": ("application/pdf",),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",),
    ".txt": ("text/plain",),
    ".md": ("text/markdown", "text/plain", "text/x-markdown"),
    ".markdown": ("text/markdown", "text/plain"),
    ".csv": ("text/csv", "text/plain", "application/vnd.ms-excel"),
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",),
    ".eml": ("message/rfc822", "text/plain"),
    ".ics": ("text/calendar", "text/plain"),
    ".mbox": ("application/mbox", "text/plain"),
}
CANONICAL_MIME = {ext: mimes[0] for ext, mimes in ALLOWED.items()}


class UploadRejected(ValueError):
    pass


@dataclass
class ValidatedUpload:
    original_filename: str
    extension: str
    mime_type: str
    size: int
    sha256: str
    storage_name: str


def sanitize_filename(name: str) -> str:
    name = unicodedata.normalize("NFKC", name or "")
    name = name.replace("\\", "/").split("/")[-1]  # drop any directory components
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    name = re.sub(r"[^\w.\- ()&,]", "_", name).strip(" .")
    if not name or name in (".", ".."):
        raise UploadRejected("invalid filename")
    return name[:200]


def _sniff(ext: str, head: bytes) -> bool:
    if ext == ".pdf":
        return head.startswith(b"%PDF-")
    if ext in (".docx", ".xlsx"):
        return head.startswith(b"PK\x03\x04")
    # Text formats: must decode as UTF-8 (or latin-1 without NULs) and contain no binary NUL bytes.
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        try:
            head[:-4].decode("utf-8")  # a multi-byte char may be cut at the boundary
        except UnicodeDecodeError:
            return False
    return True


def validate_upload(filename: str, content: bytes, declared_mime: str | None, max_bytes: int) -> ValidatedUpload:
    safe = sanitize_filename(filename)
    ext = Path(safe).suffix.lower()
    if ext not in ALLOWED:
        raise UploadRejected(f"file type {ext or '(none)'} is not supported")
    if len(content) == 0:
        raise UploadRejected("file is empty")
    if len(content) > max_bytes:
        raise UploadRejected(f"file exceeds the {max_bytes // (1024 * 1024)} MB limit")
    declared = (declared_mime or "").split(";")[0].strip().lower()
    if declared and declared not in ALLOWED[ext] and declared != "application/octet-stream":
        raise UploadRejected(f"declared type {declared} does not match {ext}")
    if not _sniff(ext, content[:4096]):
        raise UploadRejected("file content does not match its extension")
    if ext in (".docx", ".xlsx"):
        _check_zip(content)
    return ValidatedUpload(
        original_filename=safe, extension=ext, mime_type=CANONICAL_MIME[ext], size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        storage_name=f"{secrets.token_hex(16)}{ext}",  # generated; user input never becomes a path
    )


def _check_zip(content: bytes, max_ratio: int = 100, max_total: int = 500 * 1024 * 1024) -> None:
    """Reject zip bombs and path-traversal members in OOXML containers."""
    import io
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            total = 0
            for info in z.infolist():
                if info.filename.startswith("/") or ".." in Path(info.filename).parts:
                    raise UploadRejected("archive contains unsafe paths")
                total += info.file_size
                if info.compress_size and info.file_size / max(info.compress_size, 1) > max_ratio and info.file_size > 10_000_000:
                    raise UploadRejected("archive compression ratio is suspicious")
            if total > max_total:
                raise UploadRejected("archive expands beyond the size limit")
    except zipfile.BadZipFile as exc:
        raise UploadRejected("corrupt document container") from exc


def storage_path(base_dir: str, user_id: str, storage_name: str) -> Path:
    """Resolve the on-disk path and assert it stays inside the user's upload directory."""
    if not re.fullmatch(r"[0-9a-f]{32}\.[a-z]+", storage_name) or not re.fullmatch(r"[0-9a-f\-]{36}", user_id):
        raise UploadRejected("invalid storage reference")
    root = (Path(base_dir) / "uploads" / user_id).resolve()
    p = (root / storage_name).resolve()
    if root not in p.parents:
        raise UploadRejected("path escapes upload directory")
    return p
