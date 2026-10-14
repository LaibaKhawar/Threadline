"""Regression tests for issues found in the independent architecture/security audit."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agent.runtime import AgentRuntime
from app.ai.llm.gateway import set_provider_override
from app.commitments.resolution import resolve_commitments
from app.db import models as m
from app.domain.events import process_event
from app.ingestion.sync import _upsert
from app.main import app
from evals.fakes import ScriptedProvider
from tests.helpers import ALEX, SARAH, dt, email, ingest, integration, meeting


def test_findings_never_carry_text_from_a_source_with_ai_disabled(db, user, ws) -> None:
    """Audit #2: tool findings (e.g. a meeting brief's email snippets) used to bypass the per-source filter."""
    ws.settings.clock_override = dt("2026-10-14 09:00")
    db.commit()
    mail = integration(db, user.id, "gmail")
    cal = integration(db, user.id, "gcal")
    mail.local_ai_allowed = False
    ingest(db, mail, [email(SARAH, [ALEX], "Orion", "Hi Alex,\n\nI'll send the ZEBRA-PLAN-7781 criteria by Oct 16.\n\nSarah", "2026-10-07 09:00")])
    ingest(db, cal, [meeting("m1", "Orion pilot sync", "2026-10-14 11:00", "2026-10-14 11:30", [ALEX, SARAH], description="Pilot status")])
    prompts: list[str] = []
    set_provider_override("local", ScriptedProvider(fn=lambda msgs: prompts.append(msgs[-1].content) or "Brief [S1]."))
    AgentRuntime(db, user.id, use_llm=True).run("Prepare me for my 11 AM meeting")
    assert prompts, "the model should have been called"
    assert all("ZEBRA-PLAN-7781" not in p for p in prompts)


def _client(email_: str) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/auth/register", json={"email": email_, "password": "long-enough-password", "display_name": "x"})
    assert r.status_code == 200
    c.headers["x-csrf-token"] = c.cookies.get("tl_csrf")
    return c


def test_foreign_project_ids_are_rejected() -> None:
    """Audit #3: a user could attach tasks/notes to another user's project."""
    a, b = _client("a@example.com"), _client("b@example.com")
    pid = a.post("/api/projects", json={"name": "Secret"}).json()["id"]
    assert b.post("/api/tasks", json={"title": "x", "project_id": pid}).status_code == 404
    assert b.post("/api/notes", json={"title": "x", "body": "y", "project_id": pid}).status_code == 404
    own = b.post("/api/tasks", json={"title": "mine"}).json()
    assert b.patch(f"/api/tasks/{own['id']}", json={"project_id": pid}).status_code == 404


def test_user_corrections_survive_an_upstream_edit(db, user, ws) -> None:
    """Audit #4: re-syncing an edited item deleted confirmed decisions."""
    ws.settings.clock_override = dt("2026-10-14 09:00")
    db.commit()
    integ = integration(db, user.id)
    original = email(SARAH, [ALEX], "DB", "Hi Alex,\n\nWe've decided to use PostgreSQL rather than MongoDB.\n\nSarah", "2026-08-20 09:00", key="k1")
    ingest(db, integ, [original])
    d = db.scalar(select(m.Decision))
    d.user_confirmed = True
    db.commit()
    edited = email(SARAH, [ALEX], "DB", "Hi Alex,\n\nWe've decided to use PostgreSQL rather than MongoDB. (typo fixed)\n\nSarah", "2026-08-20 09:00", key="k1")
    ingest(db, integ, [edited])
    assert db.get(m.Decision, d.id) is not None


def test_user_status_change_is_not_overridden_by_resolution(db, user, ws) -> None:
    """Audit #6: reopening an auto-fulfilled commitment was undone on the next resolution pass."""
    ws.settings.clock_override = dt("2026-09-25 09:00")
    db.commit()
    integ = integration(db, user.id)
    ingest(db, integ, [
        email(SARAH, [ALEX], "Proposal", "Hi Alex,\n\nI'll send the Atlas proposal by Friday.\n\nSarah", "2026-09-15 10:00", key="p"),
        email(SARAH, [ALEX], "Re: Proposal", "Hi Alex,\n\nAttached is the final Atlas proposal.\n\nSarah", "2026-09-17 10:00",
              reply_to="p", attachments=["Atlas_proposal.pdf"]),
    ])
    c = db.scalar(select(m.Commitment))
    assert c.status == "FULFILLED"
    c.status, c.user_modified = "OPEN", True
    db.commit()
    resolve_commitments(ws)
    db.refresh(c)
    assert c.status == "OPEN"


def test_an_event_already_being_processed_is_not_processed_again(db, user) -> None:
    """Audit #5: the redelivery path ran handlers twice in parallel."""
    integ = integration(db, user.id)
    ev = None
    _upsert(db, integ, email(SARAH, [ALEX], "x", "I'll send it Friday.", "2026-09-15 10:00"))
    db.commit()
    ev = db.scalar(select(m.DomainEvent))
    ev.status = "processing"
    db.commit()
    assert process_event(db, ev.id) == "processing"
    assert db.scalar(select(m.Commitment)) is None  # the handler did not run


def test_demo_account_cannot_import_files_and_auth_rejects_cross_site_posts(db) -> None:
    """Audit #1 and #15."""
    from app.core.config import get_settings
    from app.services.accounts import create_user

    get_settings().demo_login_enabled = True
    create_user(db, email="alex@lumenlabs.io", password="demo-password-123", display_name="Alex Morgan", is_demo=True)
    db.commit()
    c = TestClient(app)
    assert c.post("/api/auth/demo", headers={"origin": "https://evil.example"}).status_code == 403
    assert c.post("/api/auth/demo").status_code == 200
    c.headers["x-csrf-token"] = c.cookies.get("tl_csrf")
    assert c.post("/api/integrations", json={"kind": "local_files", "config": {"path": "/"}}).status_code == 403
    assert c.post("/api/documents", files={"file": ("a.md", b"# hi", "text/markdown")}).status_code == 403
    get_settings().demo_login_enabled = False


def test_evaluation_processes_its_workspace_even_when_events_go_to_celery(db, user, monkeypatch) -> None:
    """In Docker (EVENTS_EAGER=false) the evaluation scored a workspace that workers had not processed yet."""
    from app.core.config import get_settings
    from app.domain.events import eager_events
    from app.workers import tasks

    queued: list[str] = []
    monkeypatch.setattr(tasks.process_event_task, "delay", lambda eid: queued.append(eid))
    monkeypatch.setattr(get_settings(), "events_eager", False)
    mail = integration(db, user.id, "gmail")
    with eager_events():
        ingest(db, mail, [email(SARAH, [ALEX], "Orion", "Hi Alex,\n\nI'll send the pilot criteria by Oct 16.\n\nSarah", "2026-10-07 09:00")])
    assert get_settings().events_eager is False, "the override must be restored"
    assert queued == []
    statuses = set(db.scalars(select(m.DomainEvent.status).where(m.DomainEvent.user_id == user.id)))
    assert statuses == {"done"}
    assert db.scalar(select(m.Commitment).where(m.Commitment.user_id == user.id)) is not None
