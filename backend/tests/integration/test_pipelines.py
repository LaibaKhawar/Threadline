"""End-to-end flows through sync -> events -> processing -> memory -> retrieval -> assistant."""

from sqlalchemy import func, select

from app.agent.runtime import AgentRuntime
from app.db import models as m
from app.ingestion.sync import run_sync
from app.intelligence.briefs import meeting_brief
from app.retrieval.hybrid import HybridRetriever
from tests.helpers import AHMED, ALEX, LAIBA, SARAH, document, dt, email, ingest, integration, meeting


def _clock(ws, s):  # type: ignore[no-untyped-def]
    ws.settings.clock_override = dt(s)
    ws.db.commit()


def test_email_sync_extraction_commitment_graph_retrieval(db, user, ws) -> None:
    _clock(ws, "2026-09-25 09:00")
    integ = integration(db, user.id)
    ingest(db, integ, [email(AHMED, [LAIBA, ALEX], "Atlas architecture review",
                             "Hi Laiba,\n\nI'll send the updated architecture document by Friday. Once you've reviewed it, please share "
                             "your feedback with Ahmed.\n\nAhmed Khan\nEngineering Manager, Lumen", "2026-09-15 10:00")])
    c = db.scalar(select(m.Commitment).where(m.Commitment.kind == "commitment"))
    assert c.action == "send" and c.due_at.date().isoformat() == "2026-09-18"
    ahmed = db.scalar(select(m.Person).where(m.Person.primary_email == "ahmed@lumen.io"))
    assert c.actor_person_id == ahmed.id
    req = db.scalar(select(m.Commitment).where(m.Commitment.kind == "request"))
    laiba = db.scalar(select(m.Person).where(m.Person.primary_email == "laiba@lumen.io"))
    assert req.actor_person_id == laiba.id  # greeting identifies the addressee among several recipients
    rels = {r.rel_type for r in db.scalars(select(m.Relationship))}
    assert {"SENT", "SENT_TO", "COMMITTED_TO", "ASSIGNED_TO", "DEPENDS_ON", "EXTRACTED_FROM", "WORKS_AT"} <= rels
    edge = db.scalar(select(m.Relationship).where(m.Relationship.rel_type == "COMMITTED_TO"))
    assert edge.evidence_span.startswith("I'll send") and edge.source_type == "email"
    # the overdue pass explains itself
    from app.commitments.resolution import resolve_commitments

    resolve_commitments(ws)
    db.refresh(c)
    assert c.status == "OVERDUE"
    hits = HybridRetriever(db, user.id, now=ws.now(), self_person_id=ws.self_person_id).search("what did Ahmed promise about the architecture document").hits
    assert hits and hits[0].type in ("commitment", "email")


def test_document_parse_embed_graph_answer(db, user, ws) -> None:
    _clock(ws, "2026-10-01 09:00")
    db.add(m.Project(user_id=user.id, name="Atlas"))
    db.commit()
    integ = integration(db, user.id)
    md = b"# Atlas design\n\n## Event store\n\nWe've decided to use PostgreSQL rather than MongoDB for the Atlas event store.\n"
    ingest(db, integ, [document("d1", "atlas_design.md", md, at="2026-09-20 10:00")])
    doc = db.scalar(select(m.Document))
    assert doc.status == "ready" and doc.project_id is not None
    chunk = db.scalar(select(m.Chunk).where(m.Chunk.owner_id == doc.id, m.Chunk.text.ilike("%PostgreSQL%")))
    assert chunk.section == "Event store" and chunk.embedding is not None
    d = db.scalar(select(m.Decision))
    assert (d.chosen, d.rejected, d.source_type) == ("PostgreSQL", ["MongoDB"], "document")
    out = AgentRuntime(db, user.id, use_llm=False).run("When did we decide to use PostgreSQL?")
    assert "PostgreSQL" in out.answer and out.citations and out.citations[0]["source_id"] == doc.id
    assert out.verification["invalid_citations"] == 0


def test_calendar_event_project_match_and_meeting_brief(db, user, ws) -> None:
    _clock(ws, "2026-10-14 09:00")
    db.add(m.Project(user_id=user.id, name="Orion"))
    db.commit()
    integ = integration(db, user.id)
    ingest(db, integ, [
        email(SARAH, [ALEX], "Orion pilot", "Hi Alex,\n\nI'll send the pilot success criteria by Oct 16.\n\nSarah", "2026-10-07 09:00"),
        meeting("m1", "Orion pilot sync", "2026-10-08 11:00", "2026-10-08 11:30", [ALEX, SARAH], notes="Discussed start dates."),
        meeting("m2", "Orion pilot sync", "2026-10-15 11:00", "2026-10-15 11:30", [ALEX, SARAH], description="Proposal and start date"),
    ])
    ev = db.scalar(select(m.CalendarEvent).where(m.CalendarEvent.start_at == dt("2026-10-15 11:00")))
    assert ev.project_id is not None
    b = meeting_brief(ws, ev.id)
    assert [p["name"] for p in b["participants"]] == ["Sarah Chen"]
    assert any("success criteria" in c["title"] for c in b["open_commitments"])
    assert b["previous_meeting"]["notes"] == "Discussed start dates."


def test_commitment_then_future_email_fulfils_it(db, user, ws) -> None:
    _clock(ws, "2026-09-20 09:00")
    integ = integration(db, user.id)
    ingest(db, integ, [email(SARAH, [ALEX], "Proposal", "Hi Alex,\n\nSarah will send the Project Atlas proposal.\n\nThanks,\nSarah", "2026-09-10 09:00", key="a")])
    c = db.scalar(select(m.Commitment))
    assert c.status == "OPEN"
    ingest(db, integ, [email(SARAH, [ALEX], "Re: Proposal", "Hi Alex,\n\nAttached is the final Project Atlas proposal.\n\nSarah", "2026-09-12 09:00",
                             reply_to="a", attachments=["Atlas_proposal.pdf"])])
    db.refresh(c)
    assert c.status == "FULFILLED"  # resolved incrementally by the ContentProcessed handler


def test_deadline_move_supersedes_without_deleting_history(db, user, ws) -> None:
    _clock(ws, "2026-10-01 09:00")
    db.add(m.Project(user_id=user.id, name="Atlas"))
    db.commit()
    integ = integration(db, user.id)
    ingest(db, integ, [
        email(ALEX, [AHMED], "Project Atlas plan", "Hi Ahmed,\n\nThe Atlas launch is scheduled for October 9.\n\nAlex", "2026-08-04 09:00"),
        email(ALEX, [AHMED], "Project Atlas timeline", "Hi Ahmed,\n\nThe Atlas launch has been moved to October 23.\n\nAlex", "2026-09-29 09:00"),
    ])
    facts = list(db.scalars(select(m.Memory).where(m.Memory.attribute.like("deadline:%")).order_by(m.Memory.valid_from)))
    assert [(f.value, f.status) for f in facts] == [("2026-10-09", "superseded"), ("2026-10-23", "active")]
    out = AgentRuntime(db, user.id, use_llm=False).run("What was the Atlas launch deadline before it was moved?")
    assert "Oct 9, 2026" in out.answer and "Oct 23, 2026" in out.answer and out.citations


def test_sync_is_idempotent_and_handles_edits_and_deletions(db, user, ws, tmp_path, monkeypatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "local_import_roots", [str(tmp_path)])
    (tmp_path / "a.txt").write_text("We will finish migration by Friday.")
    (tmp_path / "b.md").write_text("# Note\n\n- [ ] Call Sarah")
    integ = m.Integration(user_id=user.id, kind="local_files", name="folder", config={"path": str(tmp_path)})
    db.add(integ)
    db.commit()
    r1 = run_sync(db, integ.id)
    assert (r1.created, r1.unchanged) == (2, 0)
    n_chunks = db.scalar(select(func.count()).select_from(m.Chunk))
    r2 = run_sync(db, integ.id)
    assert (r2.created, r2.updated, r2.unchanged) == (0, 0, 0)  # manifest: unchanged files not even read
    assert db.scalar(select(func.count()).select_from(m.Chunk)) == n_chunks
    import time

    time.sleep(0.01)
    (tmp_path / "a.txt").write_text("We will finish the cutover by Monday.")
    (tmp_path / "b.md").unlink()
    r3 = run_sync(db, integ.id)
    assert (r3.updated, r3.deleted) == (1, 1)
    assert db.scalar(select(func.count()).select_from(m.Note)) == 0
    assert db.scalar(select(m.Document)).text.startswith("We will finish the cutover")
    st = db.scalar(select(m.SyncState))
    assert st.checkpoint["manifest"] and st.items_created == 2
