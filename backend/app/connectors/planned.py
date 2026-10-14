"""Connectors that are designed for but not implemented yet. They appear in the catalog as
'planned' and cannot be connected, so the UI never pretends they work."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from app.connectors.base import Connector, Normalized, SyncContext
from app.connectors.registry import register


class _Planned(Connector):
    implemented = False
    requires_network = True
    auth = "oauth2"

    def list_items(self, ctx: SyncContext) -> Iterator[tuple[str, str | None]]:
        raise NotImplementedError(f"{self.display_name} connector is not implemented yet")

    def get_item(self, external_id: str) -> Any:
        raise NotImplementedError

    def normalize(self, raw: Any) -> Normalized:
        raise NotImplementedError


for _kind, _name, _desc, _kinds in [
    ("outlook", "Outlook Mail", "Microsoft Graph /me/messages with delta queries.", ("email",)),
    ("mscal", "Microsoft Calendar", "Microsoft Graph calendarView delta.", ("event",)),
    ("gdrive", "Google Drive", "Drive changes API (startPageToken) for documents.", ("document",)),
    ("slack", "Slack", "conversations.history for selected channels.", ("email",)),
    ("notion", "Notion", "Pages and databases as notes.", ("note",)),
    ("github", "GitHub", "Issues and PR discussions.", ("note",)),
    ("linear", "Linear", "Issues as tasks.", ("note",)),
]:
    register(type(f"{_kind.title()}Connector", (_Planned,), {"kind": _kind, "display_name": _name,
                                                              "description": _desc, "item_kinds": _kinds}))
