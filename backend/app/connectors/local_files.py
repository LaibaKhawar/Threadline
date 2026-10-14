"""Local folder connector: documents, Markdown notes, .eml/.mbox mail and .ics calendars.

Incremental: a manifest of (size, mtime_ns) per file is the checkpoint, so unchanged files are not
re-read; content hashes then decide whether an item really changed. Files that disappear are
reported as deletions. Works fully offline.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from app.connectors.base import (
    Connector,
    ConnectorError,
    Deletion,
    Normalized,
    NormalizedDocument,
    NormalizedNote,
    SyncContext,
)
from app.connectors.formats import parse_eml, parse_ics, parse_mbox
from app.connectors.registry import register
from app.documents.validation import ALLOWED

DOC_EXT = {".pdf", ".docx", ".txt", ".csv", ".xlsx"}
MAX_FILE_BYTES = 25 * 1024 * 1024


@register
class LocalFilesConnector(Connector):
    kind = "local_files"
    display_name = "Local folder"
    description = "Index a folder on this machine: PDF, DOCX, TXT, Markdown, CSV, XLSX, .eml/.mbox mail and .ics calendars."
    item_kinds = ("document", "note", "email", "event")
    auth = "path"

    def _root(self) -> Path:
        root = Path(self.config.get("path", "")).expanduser()
        allowed = [Path(p).expanduser().resolve() for p in self.config.get("_allowed_roots", [])]
        forbidden = [Path(p).expanduser().resolve() for p in self.config.get("_forbidden_roots", [])]
        if not allowed:
            raise ConnectorError("local folder import is disabled: set LOCAL_IMPORT_ROOTS to the folders it may read", retryable=False)
        if not root.is_dir():
            raise ConnectorError(f"folder not found: {root}", retryable=False)
        r = root.resolve()
        if not any(r == a or a in r.parents for a in allowed):
            raise ConnectorError("folder is outside the allowed import roots", retryable=False)
        if any(r == f or f in r.parents or r in f.parents for f in forbidden):
            raise ConnectorError("this folder contains Threadline's own data and cannot be imported", retryable=False)
        return r

    def authenticate(self) -> dict[str, Any]:
        root = self._root()
        return {"ok": True, "path": str(root)}

    @property
    def full_listing(self) -> bool:
        return True

    def _files(self) -> Iterator[Path]:
        root = self._root()
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                p = Path(dirpath) / fn
                if fn.startswith(".") or p.is_symlink():
                    continue
                if p.suffix.lower() in ALLOWED:
                    yield p

    def list_items(self, ctx: SyncContext) -> Iterator[tuple[str, str | None]]:
        manifest = dict(ctx.checkpoint.get("manifest", {}))
        new_manifest: dict[str, str] = {}
        root = self._root()
        for p in self._files():
            st = p.stat()
            if st.st_size > MAX_FILE_BYTES:
                continue
            rel = str(p.relative_to(root))
            version = f"{st.st_size}:{st.st_mtime_ns}"
            new_manifest[rel] = version
            if manifest.get(rel) == version and any(k == rel or k.startswith(rel + "#") for k in ctx.known):
                yield rel, None  # unchanged: listed (so not deleted) but not re-read
                continue
            yield rel, version
        self.next_checkpoint = {"manifest": new_manifest}

    def sync(self, ctx: SyncContext) -> Iterator[Normalized | Deletion]:
        root = self._root()
        seen: set[str] = set()
        for rel, version in self.list_items(ctx):
            seen.add(rel)
            if version is None:
                for k in ctx.known:
                    if k == rel or k.startswith(rel + "#"):
                        seen.add(k)
                continue
            out = self.normalize(root / rel)
            for item in out if isinstance(out, list) else [out]:
                seen.add(item.external_id)
                yield item
        for ext_id in ctx.known:
            if ext_id not in seen:
                yield Deletion(ext_id)

    def get_item(self, external_id: str) -> Path:
        return self._root() / external_id

    def normalize(self, raw: Any) -> Normalized | list[Normalized]:
        p: Path = raw
        rel = str(p.relative_to(self._root()))
        ext = p.suffix.lower()
        data = p.read_bytes()
        if ext in (".md", ".markdown") and self.config.get("markdown_as", "note") == "note":
            text = data.decode("utf-8", errors="replace")
            title = next((ln[2:].strip() for ln in text.splitlines() if ln.startswith("# ")), p.stem)
            return NormalizedNote(external_id=rel, title=title, body=text)
        if ext == ".eml":
            e = parse_eml(data)
            e.external_id = f"{rel}#{e.message_id}"
            return e
        if ext == ".mbox":
            out_e = parse_mbox(str(p))
            for e in out_e:
                e.external_id = f"{rel}#{e.message_id}"
            return list(out_e)
        if ext == ".ics":
            out_v = parse_ics(data)
            for v in out_v:
                v.external_id = f"{rel}#{v.external_id}"
            return list(out_v)
        return NormalizedDocument(external_id=rel, filename=p.name, content=data)
