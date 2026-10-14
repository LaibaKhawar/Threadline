from datetime import UTC, datetime

from app.db import models as m
from app.memory.graph import GraphService
from app.memory.memories import MemoryService


def d(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


def _people(db, user):  # type: ignore[no-untyped-def]
    p = m.Person(user_id=user.id, display_name="Sarah Chen")
    a, b = m.Organization(user_id=user.id, name="Northwind"), m.Organization(user_id=user.id, name="Acme")
    db.add_all([p, a, b])
    db.flush()
    return p, a, b


def test_functional_relation_keeps_history(db, user) -> None:
    g = GraphService(db, user.id)
    p, nw, acme = _people(db, user)
    g.add_edge(("person", p.id), "WORKS_AT", ("organization", nw.id), valid_from=d("2026-03-10"))
    g.add_edge(("person", p.id), "WORKS_AT", ("organization", acme.id), valid_from=d("2026-09-02"))
    edges = sorted(g.edges_of(("person", p.id), include_history=True), key=lambda e: e.valid_from)
    assert [(e.dst_id, e.status) for e in edges] == [(nw.id, "superseded"), (acme.id, "active")]
    assert edges[0].valid_to == d("2026-09-02")
    # point-in-time queries
    assert [e.dst_id for e in g.edges_of(("person", p.id), as_of=d("2026-04-01"))] == [nw.id]
    assert [e.dst_id for e in g.edges_of(("person", p.id), as_of=d("2026-10-01"))] == [acme.id]


def test_out_of_order_facts_are_ordered_by_validity(db, user) -> None:
    g = GraphService(db, user.id)
    p, nw, acme = _people(db, user)
    g.add_edge(("person", p.id), "WORKS_AT", ("organization", acme.id), valid_from=d("2026-09-02"))
    g.add_edge(("person", p.id), "WORKS_AT", ("organization", nw.id), valid_from=d("2026-03-10"))  # learned later
    active = g.edges_of(("person", p.id))
    assert [e.dst_id for e in active] == [acme.id]


def test_user_rejected_edges_are_not_resurrected(db, user) -> None:
    g = GraphService(db, user.id)
    p, nw, _ = _people(db, user)
    e = g.add_edge(("person", p.id), "MENTIONS", ("organization", nw.id), source=("email", "x"))
    g.reject_edge(e.id)
    again = g.add_edge(("person", p.id), "MENTIONS", ("organization", nw.id), source=("email", "x"))
    assert again.status == "rejected"
    assert g.edges_of(("person", p.id)) == []


def test_neighbourhood_returns_labels_and_evidence(db, user) -> None:
    g = GraphService(db, user.id)
    p, nw, _ = _people(db, user)
    g.add_edge(("person", p.id), "WORKS_AT", ("organization", nw.id), source=("email", "e1"), span="Northwind signature")
    nb = g.neighborhood(("person", p.id))
    assert {n["label"] for n in nb["nodes"]} == {"Sarah Chen", "Northwind"}
    assert nb["edges"][0]["evidence"]["span"] == "Northwind signature"


def test_memory_supersession_and_history(db, user) -> None:
    mem = MemoryService(db, user.id)
    subj = ("project", "p1")
    mem.record_fact(subject=subj, attribute="deadline:launch", value="2026-10-09", content="launch Oct 9", valid_from=d("2026-08-04"),
                    observed_at=d("2026-08-04"), source=("email", "a"), span="scheduled for October 9")
    mem.record_fact(subject=subj, attribute="deadline:launch", value="2026-10-23", content="launch Oct 23", valid_from=d("2026-09-29"),
                    observed_at=d("2026-09-29"), source=("email", "b"), span="moved to October 23")
    hist = mem.history(subj, "deadline:launch")
    assert [(h.value, h.status) for h in hist] == [("2026-10-09", "superseded"), ("2026-10-23", "active")]
    assert mem.value_at(subj, "deadline:launch", d("2026-09-01")).value == "2026-10-09"
    assert mem.value_at(subj, "deadline:launch", d("2026-10-01")).value == "2026-10-23"


def test_memory_reinforcement_and_consolidation(db, user) -> None:
    mem = MemoryService(db, user.id)
    subj = ("person", "p1")
    a = mem.record_fact(subject=subj, attribute="works_at", value="Acme", content="x", valid_from=d("2026-09-02"),
                        observed_at=d("2026-09-02"), source=("email", "a"), span=None)
    b = mem.record_fact(subject=subj, attribute="works_at", value="acme", content="x", valid_from=d("2026-09-05"),
                        observed_at=d("2026-09-05"), source=("email", "b"), span=None)
    assert a.id == b.id and a.reinforcement_count == 2
    mem.record_episode(content="old meeting", occurred_at=d("2025-01-01"), subject=None, source=None, confidence=0.5)
    db.flush()
    stats = mem.consolidate(d("2026-10-14"))
    assert stats["archived"] == 1
    mem.add_procedural("Always show evidence")
    assert mem.procedural() == ["Always show evidence"]
