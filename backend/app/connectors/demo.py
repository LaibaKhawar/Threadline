"""Synthetic demo workspace as a connector (so the demo exercises the real sync + processing path)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.connectors.base import (
    Connector,
    Deletion,
    Normalized,
    NormalizedDocument,
    NormalizedEmail,
    NormalizedEvent,
    NormalizedNote,
    SyncContext,
)
from app.connectors.registry import register
from app.demo import world

FILES = Path(__file__).resolve().parents[2] / "demo_data" / "files"


def _dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)


def demo_message_id(key: str) -> str:
    return f"<{key}@demo.threadline.local>"


@register
class DemoWorkspaceConnector(Connector):
    kind = "demo"
    display_name = "Demo workspace"
    description = "Synthetic workspace for Alex Morgan (fictional people, projects, emails, meetings, documents)."
    item_kinds = ("email", "event", "document", "note")

    @property
    def full_listing(self) -> bool:
        return True

    def _all(self) -> list[Normalized]:
        out: list[Normalized] = []
        until = self.config.get("until")  # used by tests to sync the world in two phases
        for e in world.EMAILS:
            if until and e["sent_at"] > until:
                continue
            refs = [demo_message_id(e["in_reply_to"])] if e.get("in_reply_to") else []
            out.append(NormalizedEmail(
                external_id=e["key"], message_id=demo_message_id(e["key"]), subject=e["subject"], body=e["body"],
                from_addr=e["from"]["email"], from_name=e["from"]["name"], to=e["to"], cc=e["cc"], sent_at=_dt(e["sent_at"]),
                in_reply_to=refs[0] if refs else None, references=refs, attachments=e["attachments"],
            ))
        for ev in world.EVENTS:
            if until and ev["start"] > until:
                continue
            out.append(NormalizedEvent(
                external_id=ev["key"], title=ev["title"], start_at=_dt(ev["start"]), end_at=_dt(ev["end"]),
                description=ev["description"] or None, location=ev["location"],
                attendees=[{"email": a["email"], "name": a["name"], "response": "accepted"} for a in ev["attendees"]],
                organizer=ev["organizer"], notes=ev["notes"],
            ))
        for d in world.DOCUMENTS:
            if until and d["authored_at"] > until:
                continue
            out.append(NormalizedDocument(external_id=d["key"], filename=d["filename"], content=(FILES / d["filename"]).read_bytes(),
                                          author=d["author"], authored_at=_dt(d["authored_at"])))
        for n in world.NOTES:
            out.append(NormalizedNote(external_id=n["key"], title=n["title"], body=n["body"], tags=n["tags"], project=n["project"],
                                      external_updated_at=_dt(n["updated_at"])))
        return out

    def list_items(self, ctx: SyncContext) -> Iterator[tuple[str, str | None]]:
        for item in self._all():
            yield item.external_id, None

    def get_item(self, external_id: str) -> Any:
        return next(i for i in self._all() if i.external_id == external_id)

    def normalize(self, raw: Any) -> Normalized:
        return raw

    def sync(self, ctx: SyncContext) -> Iterator[Normalized | Deletion]:
        items = self._all()
        ids = {i.external_id for i in items}
        yield from sorted(items, key=_order)
        for k in ctx.known:
            if k not in ids:
                yield Deletion(k)


def _order(item: Normalized) -> tuple[int, datetime]:
    # Documents and notes first so emails can link attachments; then chronological.
    if isinstance(item, NormalizedDocument):
        return (0, item.authored_at or datetime.min.replace(tzinfo=UTC))
    if isinstance(item, NormalizedNote):
        return (3, datetime.max.replace(tzinfo=UTC))
    if isinstance(item, NormalizedEmail):
        return (1, item.sent_at)
    return (1, item.start_at)  # type: ignore[union-attr]
