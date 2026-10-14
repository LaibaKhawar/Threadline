from sqlalchemy import select

from app.commitments.resolution import resolve_commitments
from app.db import models as m
from app.ingestion.workspace import Workspace
from tests.helpers import AHMED, ALEX, LAIBA, SARAH, dt, email, ingest, integration


def _setup(db, user, clock: str):  # type: ignore[no-untyped-def]
    ws = Workspace(db, user.id)
    ws.settings.clock_override = dt(clock)
    db.commit()
    return ws, integration(db, user.id)


def _commitment(db, user, obj: str) -> m.Commitment:  # type: ignore[no-untyped-def]
    return db.scalar(select(m.Commitment).where(m.Commitment.user_id == user.id, m.Commitment.object.ilike(f"%{obj}%")))


def test_promise_then_delivery_is_fulfilled_with_evidence(db, user) -> None:
    ws, integ = _setup(db, user, "2026-09-25 09:00")
    ingest(db, integ, [
        email(SARAH, [ALEX], "Atlas proposal", "Hi Alex,\n\nI'll send the Project Atlas proposal by Friday.\n\nSarah", "2026-09-15 10:00", key="p"),
        email(SARAH, [ALEX], "Re: Atlas proposal", "Hi Alex,\n\nAttached is the final Project Atlas proposal.\n\nSarah", "2026-09-17 10:00",
              reply_to="p", attachments=["Atlas_proposal.pdf"], key="f"),
    ])
    resolve_commitments(ws)
    c = _commitment(db, user, "proposal")
    assert c.status == "FULFILLED" and c.resolution_confidence >= 0.7
    roles = {e.role for e in db.scalars(select(m.Evidence).where(m.Evidence.subject_id == c.id))}
    assert {"source", "fulfillment"} <= roles
    assert "completion statement" in c.resolution_reason


def test_missing_delivery_after_deadline_is_overdue_with_explanation(db, user) -> None:
    ws, integ = _setup(db, user, "2026-09-25 09:00")
    ingest(db, integ, [email(AHMED, [LAIBA], "Architecture", "Hi Laiba,\n\nI'll send the updated architecture document by Friday.\n\nAhmed",
                             "2026-09-15 10:00")])
    resolve_commitments(ws)
    c = _commitment(db, user, "architecture")
    assert c.status == "OVERDUE"
    assert "no later email" in c.resolution_reason and "Sep 18, 2026" in c.resolution_reason


def test_restating_the_promise_is_not_fulfilment(db, user) -> None:
    ws, integ = _setup(db, user, "2026-10-14 09:00")
    ingest(db, integ, [
        email(AHMED, [ALEX], "Runbook", "Hi Alex,\n\nI'll share the migration runbook by Oct 2.\n\nAhmed", "2026-09-24 09:00"),
        email(AHMED, [ALEX], "Runbook status", "Hi Alex,\n\nThe migration runbook is still in progress, I'll get it to you soon.\n\nAhmed", "2026-10-03 09:00"),
    ])
    resolve_commitments(ws)
    assert _commitment(db, user, "runbook").status == "OVERDUE"


def test_cancellation_by_recipient(db, user) -> None:
    ws, integ = _setup(db, user, "2026-10-14 09:00")
    ingest(db, integ, [
        email(("Priya Nair", "priya@lumen.io"), [ALEX], "Teardown", "Hi Alex,\n\nI'll put together the competitor teardown deck by Sep 24.\n\nPriya",
              "2026-09-14 09:00", key="t"),
        email(ALEX, [("Priya Nair", "priya@lumen.io")], "Re: Teardown", "Hi Priya,\n\nWe no longer need the competitor teardown deck.\n\nAlex",
              "2026-09-17 09:00", reply_to="t"),
    ])
    resolve_commitments(ws)
    c = _commitment(db, user, "teardown")
    assert c.status == "CANCELLED" and "no longer need" in c.resolution_reason


def test_hedged_intention_never_becomes_overdue(db, user) -> None:
    ws, integ = _setup(db, user, "2026-12-31 09:00")
    ingest(db, integ, [email(SARAH, [ALEX], "Ideas", "Hi Alex,\n\nMaybe we can run a usability study next month.\n\nSarah", "2026-09-26 09:00")])
    resolve_commitments(ws)
    assert _commitment(db, user, "usability").status == "UNCERTAIN"


def test_unrelated_delivery_does_not_fulfil(db, user) -> None:
    ws, integ = _setup(db, user, "2026-10-14 09:00")
    ingest(db, integ, [
        email(ALEX, [SARAH], "Pilot", "Hi Sarah,\n\nI'll send the pilot proposal by Oct 13.\n\nAlex", "2026-10-06 09:00"),
        email(ALEX, [SARAH], "Phoenix", "Hi Sarah,\n\nAttached is the Phoenix proposal.\n\nAlex", "2026-10-07 09:00", attachments=["Phoenix_Proposal.docx"]),
    ])
    resolve_commitments(ws)
    assert _commitment(db, user, "pilot proposal").status == "OVERDUE"
