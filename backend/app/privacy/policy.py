"""Privacy policy: the single deterministic gate between personal data and any model.

Rules (enforced here, tested in tests/test_privacy.py):
  * LOCAL   - every LLM call goes to the local provider. Zero cloud calls, whatever else is set.
  * HYBRID  - cloud only for operations the user allow-listed AND only if every source whose content
              is in the prompt has "cloud AI allowed". Otherwise local.
  * CLOUD   - cloud when configured, but still only for sources that allow cloud; otherwise local.
  * A source with "local AI allowed" off is never placed in any prompt (filtered before prompting;
    the gateway refuses if it slips through).
  * Embeddings are always computed locally.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Integration, UserSettings

Locality = Literal["local", "cloud"]
CLOUD_ELIGIBLE_OPERATIONS = ("answer_synthesis", "meeting_brief", "summarize", "extraction", "planning", "briefing")


@dataclass
class RouteDecision:
    locality: Locality
    reason: str


@dataclass
class SourcePolicy:
    integration_id: str
    name: str
    kind: str
    store_locally: bool
    local_ai: bool
    cloud_ai: bool


UNKNOWN_SOURCE = "unknown-source"  # content whose origin cannot be determined: never cloud, never AI


def integration_of(db: Session, source_type: str | None, source_id: str | None) -> str | None:
    """Which integration a content item came from, via its SourceItem (not via chunks, which can be missing).

    Returns None for in-app items with no source (tasks, commitments typed by the user), and
    UNKNOWN_SOURCE when a content item's origin cannot be resolved, so the policy fails closed."""
    from app.db import models as mm

    models: dict[str, mm.ContentModel] = {"email": mm.Email, "event": mm.CalendarEvent, "document": mm.Document, "note": mm.Note}
    model = models.get(source_type or "")
    if model is None or not source_id:
        return None
    si_id = db.scalar(select(model.source_item_id).where(model.id == source_id))
    if si_id is None:
        return UNKNOWN_SOURCE
    return db.scalar(select(mm.SourceItem.integration_id).where(mm.SourceItem.id == si_id)) or UNKNOWN_SOURCE


class PrivacyPolicy:
    def __init__(self, db: Session, user_id: str) -> None:
        self.db = db
        self.user_id = user_id
        self.settings = db.get(UserSettings, user_id)
        self.sources: dict[str, SourcePolicy] = {
            i.id: SourcePolicy(i.id, i.name, i.kind, i.store_locally, i.local_ai_allowed, i.cloud_ai_allowed)
            for i in db.scalars(select(Integration).where(Integration.user_id == user_id))
        }

    @property
    def mode(self) -> str:
        return self.settings.ai_mode if self.settings else get_settings().default_ai_mode

    def local_ai_allowed(self, integration_id: str | None) -> bool:
        if integration_id is None:
            return True
        src = self.sources.get(integration_id)
        return src.local_ai if src else False

    def cloud_ai_allowed(self, integration_id: str | None) -> bool:
        if integration_id is None:
            return False
        src = self.sources.get(integration_id)
        return bool(src and src.cloud_ai and src.local_ai)

    def filter_for_prompt(self, items: list[Any], locality: Locality) -> tuple[list[Any], int]:
        """Drop items whose source forbids this kind of AI processing. Returns (kept, dropped_count)."""
        kept = []
        for it in items:
            iid = it.get("integration_id") if isinstance(it, dict) else getattr(it, "integration_id", None)
            ok = self.cloud_ai_allowed(iid) if locality == "cloud" else self.local_ai_allowed(iid)
            if ok:
                kept.append(it)
        return kept, len(items) - len(kept)

    def route(self, operation: str, integration_ids: set[str | None]) -> RouteDecision:
        s = get_settings()
        mode = self.mode
        if mode == "LOCAL":
            return RouteDecision("local", "AI mode is LOCAL ONLY")
        if not s.cloud_configured:
            return RouteDecision("local", "no cloud provider is configured")
        if mode == "HYBRID":
            allowed_ops = set(self.settings.cloud_allowed_operations if self.settings else [])
            if operation not in allowed_ops:
                return RouteDecision("local", f"HYBRID mode: '{operation}' is not allow-listed for cloud")
        blocked = [i for i in integration_ids if not self.cloud_ai_allowed(i)]
        if blocked:
            names = sorted({self.sources[i].name if i in self.sources else "in-app content" for i in blocked})
            return RouteDecision("local", "sources not allowed for cloud AI: " + ", ".join(names))
        return RouteDecision("cloud", f"{mode} mode and every source in context allows cloud AI")
