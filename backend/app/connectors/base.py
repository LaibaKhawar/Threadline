"""Connector interface. Adding a source = subclass Connector, register it, done.

    authenticate()  -> verify credentials / scopes
    list_items()    -> lightweight refs (id + version) since a cursor
    get_item()      -> fetch one item
    normalize()     -> provider payload -> Normalized* (provider-neutral)
    sync()          -> generator of Normalized* / Deletion, honouring the incremental cursor
    checkpoint()    -> cursor to persist (Gmail historyId, Calendar syncToken, file manifest…)
    revoke()        -> drop tokens upstream where supported
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, ClassVar


@dataclass
class NormalizedEmail:
    external_id: str
    message_id: str
    subject: str
    body: str
    from_addr: str
    from_name: str | None
    to: list[dict[str, str]]
    cc: list[dict[str, str]]
    sent_at: datetime
    in_reply_to: str | None = None
    references: list[str] = field(default_factory=list)
    attachments: list[dict[str, Any]] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    external_updated_at: datetime | None = None
    kind: ClassVar[str] = "email"


@dataclass
class NormalizedEvent:
    external_id: str
    title: str
    start_at: datetime
    end_at: datetime
    description: str | None = None
    location: str | None = None
    attendees: list[dict[str, str]] = field(default_factory=list)
    organizer: str | None = None
    notes: str | None = None
    status: str = "confirmed"
    external_updated_at: datetime | None = None
    kind: ClassVar[str] = "event"


@dataclass
class NormalizedDocument:
    external_id: str
    filename: str
    content: bytes
    mime_type: str | None = None
    title: str | None = None
    author: str | None = None
    authored_at: datetime | None = None
    external_updated_at: datetime | None = None
    kind: ClassVar[str] = "document"


@dataclass
class NormalizedNote:
    external_id: str
    title: str
    body: str
    tags: list[str] = field(default_factory=list)
    project: str | None = None
    external_updated_at: datetime | None = None
    kind: ClassVar[str] = "note"


@dataclass
class Deletion:
    external_id: str


Normalized = NormalizedEmail | NormalizedEvent | NormalizedDocument | NormalizedNote


def content_hash(item: Normalized) -> str:
    d = asdict(item)
    d.pop("external_updated_at", None)
    d.pop("labels", None)  # read/starred state changes must not trigger a rebuild
    if isinstance(item, NormalizedDocument):
        d["content"] = hashlib.sha256(item.content).hexdigest()
    return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


class ConnectorError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class RateLimited(ConnectorError):
    def __init__(self, retry_after: float) -> None:
        super().__init__(f"rate limited; retry after {retry_after:.0f}s", retryable=True)
        self.retry_after = retry_after


@dataclass
class SyncContext:
    cursor: str | None
    checkpoint: dict[str, Any]
    known: dict[str, str]  # external_id -> content_hash already stored (for skip/deletion detection)


class Connector(ABC):
    kind: ClassVar[str]
    display_name: ClassVar[str]
    description: ClassVar[str] = ""
    item_kinds: ClassVar[tuple[str, ...]] = ()
    requires_network: ClassVar[bool] = False
    supports_incremental: ClassVar[bool] = True
    auth: ClassVar[str] = "none"  # none | oauth2 | path
    implemented: ClassVar[bool] = True

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.credentials = credentials or {}
        self.next_cursor: str | None = None
        self.next_checkpoint: dict[str, Any] = {}
        self.rate_limit_remaining: int | None = None

    def authenticate(self) -> dict[str, Any]:
        return {"ok": True}

    @abstractmethod
    def list_items(self, ctx: SyncContext) -> Iterator[tuple[str, str | None]]:
        """Yield (external_id, version) for items changed since ctx.cursor."""

    @abstractmethod
    def get_item(self, external_id: str) -> Any: ...

    @abstractmethod
    def normalize(self, raw: Any) -> Normalized | list[Normalized]: ...

    def sync(self, ctx: SyncContext) -> Iterator[Normalized | Deletion]:
        seen: set[str] = set()
        for ext_id, _version in self.list_items(ctx):
            seen.add(ext_id)
            out = self.normalize(self.get_item(ext_id))
            yield from (out if isinstance(out, list) else [out])
        if self.full_listing:
            for ext_id in ctx.known:
                if ext_id not in seen and not any(ext_id.startswith(s + "#") for s in seen):
                    yield Deletion(ext_id)

    @property
    def full_listing(self) -> bool:
        """True when list_items enumerates everything (so missing ids mean deleted)."""
        return False

    def checkpoint(self) -> tuple[str | None, dict[str, Any]]:
        return self.next_cursor, self.next_checkpoint

    def revoke(self) -> None:
        return None
