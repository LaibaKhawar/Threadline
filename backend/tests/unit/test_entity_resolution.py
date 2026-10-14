from sqlalchemy import select

from app.db import models as m
from app.resolution.entity_resolution import EntityResolver, org_key


def test_email_name_and_first_name_resolve_to_one_person(db, user) -> None:
    r = EntityResolver(db, user.id)
    a = r.resolve_person("Ahmed Khan", "ahmed@company.com")
    assert a.created
    assert r.resolve_person(None, "ahmed@company.com").person_id == a.person_id
    assert r.resolve_person("Ahmed Khan").person_id == a.person_id
    # a bare first name links only when unambiguous and is never used to create a person
    assert r.resolve_person("Ahmed", create=False).person_id == a.person_id
    assert db.scalar(select(m.Person).where(m.Person.display_name == "Ahmed")) is None


def test_same_name_different_domain_is_a_merge_candidate_not_a_merge(db, user) -> None:
    r = EntityResolver(db, user.id)
    work = r.resolve_person("Ahmed Khan", "ahmed@company.com")
    personal = r.resolve_person("Ahmed Khan", "ahmed.khan@gmail.com")
    assert personal.created and personal.person_id != work.person_id
    cand = db.scalar(select(m.MergeCandidate))
    assert cand and {cand.person_a_id, cand.person_b_id} == {work.person_id, personal.person_id}
    assert 0.6 <= cand.score < 0.9


def test_similar_names_at_different_orgs_are_not_merged(db, user) -> None:
    r = EntityResolver(db, user.id)
    daniel = r.resolve_person("Daniel Smith", "daniel.smith@lumen.io")
    dan = r.resolve_person("Dan Smith", "dan.smith@vertexcap.com")
    assert dan.person_id != daniel.person_id
    assert r.resolve_person("Dan", create=False).person_id == dan.person_id
    assert r.resolve_person("Daniel", create=False).person_id == daniel.person_id


def test_ambiguous_first_name_is_not_linked(db, user) -> None:
    r = EntityResolver(db, user.id)
    r.resolve_person("Sarah Chen", "sarah@a.com")
    r.resolve_person("Sarah Jones", "sarah@b.com")
    res = r.resolve_person("Sarah", create=False)
    assert res.person_id is None and len(res.ambiguous_ids) == 2
    # ...unless exactly one of them is in the conversation
    jones = r.resolve_person(None, "sarah@b.com").person_id
    assert r.resolve_person("Sarah", context_ids={jones}, create=False).person_id == jones


def test_email_local_part_matches_known_name_at_same_domain(db, user) -> None:
    r = EntityResolver(db, user.id)
    p = r.resolve_person("Maya Rodriguez", "maya.rodriguez@studio.co")
    assert r.resolve_person(None, "maya.r@studio.co").person_id == p.person_id


def test_manual_merge_and_split(db, user) -> None:
    r = EntityResolver(db, user.id)
    a = r.resolve_person("Ahmed Khan", "ahmed@company.com").person_id
    b = r.resolve_person("Ahmed Khan", "ahmed.khan@gmail.com").person_id
    r.merge(a, b)
    assert r.resolve_person(None, "ahmed.khan@gmail.com").person_id == a
    alias = db.scalar(select(m.PersonAlias).where(m.PersonAlias.alias_norm == "ahmed.khan@gmail.com"))
    new = r.split(a, [alias.id], "Ahmed K. (personal)")
    assert r.resolve_person(None, "ahmed.khan@gmail.com").person_id == new.id
    # a split pair is recorded as rejected so it is never proposed again
    assert db.scalar(select(m.MergeCandidate).where(m.MergeCandidate.status == "rejected"))


def test_org_resolution_normalises_names_and_domains(db, user) -> None:
    r = EntityResolver(db, user.id)
    o = r.resolve_org(None, "acmecorp.com")
    assert r.resolve_org("Acme Corp").id == o.id
    assert o.name == "Acme Corp"  # domain-derived name upgraded to the real one
    assert org_key("Lumen Labs") == org_key("lumenlabs")
