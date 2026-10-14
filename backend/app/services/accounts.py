"""Account bootstrap and the demo workspace loader."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db import models as m
from app.demo import world
from app.ingestion.workspace import Workspace

INTERNAL_SOURCES = [("notes", "Threadline notes"), ("uploads", "Uploaded files")]


def internal_integration(db: Session, user_id: str, kind: str) -> m.Integration:
    integ = db.scalar(select(m.Integration).where(m.Integration.user_id == user_id, m.Integration.kind == kind))
    if integ is None:
        name = dict(INTERNAL_SOURCES)[kind]
        integ = m.Integration(user_id=user_id, kind=kind, name=name, status="connected", config={},
                              store_locally=True, local_ai_allowed=True, cloud_ai_allowed=False)
        db.add(integ)
        db.flush()
    return integ


def create_user(db: Session, *, email: str, password: str, display_name: str, is_demo: bool = False,
                role: str = "user") -> m.User:
    user = m.User(email=email.lower().strip(), password_hash=hash_password(password), display_name=display_name,
                  is_demo=is_demo, role=role)
    db.add(user)
    db.flush()
    db.add(m.UserSettings(user_id=user.id, ai_mode="LOCAL", self_emails=[user.email]))
    db.flush()
    for kind, _ in INTERNAL_SOURCES:
        internal_integration(db, user.id, kind)
    ws = Workspace(db, user.id)
    ws.ensure_self_person(display_name, [user.email])
    db.add(m.AuditLog(user_id=user.id, actor="system", action="user_created", details={"demo": is_demo}))
    return user


def load_demo_workspace(db: Session, user: m.User, *, until: str | None = None, sync: bool = True) -> m.Integration:
    """Create projects, contacts and tasks for the demo persona, then sync the demo connector."""
    from app.ingestion.sync import run_sync

    ws = Workspace(db, user.id)
    ws.settings.clock_override = world.DEMO_NOW
    ws.settings.timezone = "UTC"
    ws.settings.self_emails = [world.SELF["email"]]
    me = ws.ensure_self_person(world.SELF["name"], [world.SELF["email"]])
    ws.resolver._add_aliases(me.id, world.SELF["name"], world.SELF["email"], None)  # persona address = you
    me.title = world.SELF["title"]
    org = ws.resolver.resolve_org(world.SELF["org"], "lumenlabs.io")
    if org:
        me.organization_id = org.id
    for name, domain in world.ORGS:
        ws.resolver.resolve_org(name, domain)
    projects: dict[str, m.Project] = {}
    for p in world.PROJECTS:
        proj = db.scalar(select(m.Project).where(m.Project.user_id == user.id, m.Project.name == p["name"]))
        if proj is None:
            proj = m.Project(user_id=user.id, name=p["name"], description=p["description"], keywords=p["keywords"],
                             color=p["color"])
            db.add(proj)
            db.flush()
        projects[p["name"]] = proj
    # Contacts the user already knows (like an address book import): canonical names + primary emails.
    for key, person in world.PEOPLE.items():
        if key == "alex":
            continue
        emails = person.get("contact_emails", person["emails"][:1])
        res = ws.resolver.resolve_person(person["name"], emails[0])
        if res.person_id is None:  # unresolvable contact: nothing to alias or annotate
            continue
        for extra in emails[1:]:
            ws.resolver._add_aliases(res.person_id, person["name"], extra, None)  # address book lists both
        contact = db.get(m.Person, res.person_id)
        if contact is not None:
            contact.created_by = "contacts"
            org = ws.resolver.resolve_org(person["org"])
            contact.organization_id = org.id if org else None
    for p in world.PROJECTS:
        for key in p["members"]:
            res = ws.resolver.resolve_person(world.PEOPLE[key]["name"], world.PEOPLE[key]["emails"][0])
            if res.person_id and db.get(m.ProjectMember, (projects[p["name"]].id, res.person_id)) is None:
                db.add(m.ProjectMember(project_id=projects[p["name"]].id, person_id=res.person_id, source="user"))
    from datetime import UTC, datetime

    for t in world.TASKS:
        if db.scalar(select(m.Task).where(m.Task.user_id == user.id, m.Task.title == t["title"])):
            continue
        db.add(m.Task(user_id=user.id, title=t["title"], project_id=projects[t["project"]].id if t["project"] else None,
                      owner_person_id=me.id, status=t["status"], priority=t["priority"], manually_created=True,
                      due_at=datetime.strptime(t["due"], "%Y-%m-%d").replace(hour=17, tzinfo=UTC) if t["due"] else None))
    integ = db.scalar(select(m.Integration).where(m.Integration.user_id == user.id, m.Integration.kind == "demo"))
    if integ is None:
        integ = m.Integration(user_id=user.id, kind="demo", name="Demo workspace", status="connected",
                              config={"until": until} if until else {}, store_locally=True, local_ai_allowed=True,
                              cloud_ai_allowed=False)
        db.add(integ)
    ws.settings.onboarding_completed = True
    db.commit()
    if sync:
        run_sync(db, integ.id)
    return integ
