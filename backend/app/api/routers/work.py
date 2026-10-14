"""Tasks, projects, commitments, decisions, inferences. Every user correction is recorded and outranks
model inference on later processing passes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.api.deps import workspace
from app.api.serialize import (
    commitment_dict,
    decision_dict,
    document_dict,
    email_dict,
    event_dict,
    iso,
    note_dict,
    person_brief,
    task_dict,
)
from app.db import models as m
from app.ingestion.workspace import Workspace
from app.intelligence.proactive import project_health

router = APIRouter(prefix="/api", tags=["work"])


def _own(ws: Workspace, model: Any, oid: str) -> Any:
    row = ws.db.get(model, oid)
    if row is None or row.user_id != ws.user_id:
        raise HTTPException(404, "not found")
    return row


def _correct(ws: Workspace, kind: str, target_type: str, target_id: str, before: dict[str, Any], after: dict[str, Any],
             rule_key: str | None = None) -> None:
    ws.db.add(m.Correction(user_id=ws.user_id, kind=kind, target_type=target_type, target_id=target_id, before=before,
                           after=after, rule_key=rule_key))
    ws.db.add(m.AuditLog(user_id=ws.user_id, actor="user", action=f"correction:{kind}", target_type=target_type,
                         target_id=target_id, details={"before": before, "after": after}))


# ------------------------------------------------------------------------------------- tasks


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    project_id: str | None = None
    priority: str = Field(default="medium", pattern="^(low|medium|high|urgent)$")
    due_at: datetime | None = None
    status: str = Field(default="active", pattern="^(active|blocked|done)$")


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    description: str | None = None
    project_id: str | None = None
    priority: str | None = Field(default=None, pattern="^(low|medium|high|urgent)$")
    due_at: datetime | None = None
    status: str | None = Field(default=None, pattern="^(suggested|active|blocked|done|dismissed)$")
    clear_due: bool = False


@router.get("/tasks")
def tasks(status: str | None = None, project_id: str | None = None, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    q = select(m.Task).where(m.Task.user_id == ws.user_id)
    if status:
        q = q.where(m.Task.status.in_(status.split(",")))
    if project_id:
        q = q.where(m.Task.project_id == project_id)
    rows = list(ws.db.scalars(q.order_by(m.Task.due_at.asc().nullslast(), m.Task.created_at.desc()).limit(500)))
    return {"now": ws.now().isoformat(), "auto_create": ws.settings.auto_create_tasks, "items": [task_dict(ws.db, t) for t in rows]}


def _check_project(ws: Workspace, project_id: str | None) -> None:
    if project_id:
        _own(ws, m.Project, project_id)


@router.post("/tasks")
def create_task(body: TaskIn, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    _check_project(ws, body.project_id)
    t = m.Task(user_id=ws.user_id, title=body.title, description=body.description, project_id=body.project_id, priority=body.priority,
               due_at=body.due_at, status=body.status, manually_created=True, owner_person_id=ws.self_person_id)
    ws.db.add(t)
    ws.db.commit()
    return task_dict(ws.db, t)


@router.patch("/tasks/{tid}")
def patch_task(tid: str, body: TaskPatch, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    t = _own(ws, m.Task, tid)
    _check_project(ws, body.project_id)
    before = {"status": t.status, "title": t.title, "due_at": iso(t.due_at), "project_id": t.project_id}
    data = body.model_dump(exclude_unset=True)
    for k in ("title", "description", "project_id", "priority", "due_at", "status"):
        if k in data and (data[k] is not None or k == "project_id"):
            setattr(t, k, data[k])
    if body.clear_due:
        t.due_at = None
    if t.status == "done" and not t.completed_at:
        t.completed_at = ws.now()
    if t.ai_suggested:
        t.user_modified = True
        kind = "task_confirmed" if before["status"] == "suggested" and t.status == "active" else (
            "task_dismissed" if t.status == "dismissed" else "task_edited")
        _correct(ws, kind, "task", t.id, before, {"status": t.status, "title": t.title, "due_at": iso(t.due_at), "project_id": t.project_id})
    ws.db.commit()
    return task_dict(ws.db, t)


@router.delete("/tasks/{tid}")
def delete_task(tid: str, ws: Workspace = Depends(workspace)) -> dict[str, bool]:
    t = _own(ws, m.Task, tid)
    if t.ai_suggested:  # keep a tombstone so re-extraction does not resurrect it
        t.status, t.user_modified = "dismissed", True
    else:
        ws.db.delete(t)
    ws.db.commit()
    return {"ok": True}


class AutoCreate(BaseModel):
    enabled: bool


@router.put("/tasks/settings/auto-create")
def set_auto_create(body: AutoCreate, ws: Workspace = Depends(workspace)) -> dict[str, bool]:
    ws.settings.auto_create_tasks = body.enabled
    ws.db.commit()
    return {"auto_create": body.enabled}


# ------------------------------------------------------------------------------------- projects


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    keywords: list[str] = Field(default_factory=list)
    color: str | None = Field(default=None, max_length=20)


class ProjectPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    keywords: list[str] | None = None
    color: str | None = None
    status_manual: str | None = Field(default=None, pattern="^(on_track|attention|at_risk|done|paused|auto)$")
    archived: bool | None = None


def _project_summary(ws: Workspace, p: m.Project) -> dict[str, Any]:
    db = ws.db
    h = project_health(ws, p)
    open_tasks = db.scalar(select(func.count()).select_from(m.Task).where(m.Task.project_id == p.id, m.Task.status.in_(["active", "blocked"]))) or 0
    overdue_c = db.scalar(select(func.count()).select_from(m.Commitment).where(m.Commitment.project_id == p.id, m.Commitment.status == "OVERDUE")) or 0
    recent_dec = db.scalar(select(func.count()).select_from(m.Decision).where(m.Decision.project_id == p.id, m.Decision.decided_at <= ws.now())) or 0
    upcoming = db.scalar(select(m.CalendarEvent).where(m.CalendarEvent.project_id == p.id, m.CalendarEvent.start_at >= ws.now())
                         .order_by(m.CalendarEvent.start_at).limit(1))
    members = [person_brief(db, pm.person_id) for pm in db.scalars(select(m.ProjectMember).where(m.ProjectMember.project_id == p.id))]
    return {"id": p.id, "name": p.name, "description": p.description, "keywords": p.keywords, "color": p.color, "archived": p.archived,
            "status_manual": p.status_manual, "health": {"status": h.status, "label": h.label, "score": h.score, "signals": h.signals},
            "open_tasks": open_tasks, "overdue_commitments": overdue_c, "decisions": recent_dec,
            "upcoming_meeting": {"id": upcoming.id, "title": upcoming.title, "start_at": iso(upcoming.start_at)} if upcoming else None,
            "members": [x for x in members if x]}


@router.get("/projects")
def projects(ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    rows = list(ws.db.scalars(select(m.Project).where(m.Project.user_id == ws.user_id).order_by(m.Project.archived, m.Project.name)))
    return {"items": [_project_summary(ws, p) for p in rows]}


@router.post("/projects")
def create_project(body: ProjectIn, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    if ws.db.scalar(select(m.Project).where(m.Project.user_id == ws.user_id, m.Project.name == body.name)):
        raise HTTPException(409, "a project with this name exists")
    p = m.Project(user_id=ws.user_id, name=body.name, description=body.description, keywords=body.keywords, color=body.color)
    ws.db.add(p)
    ws.db.commit()
    return _project_summary(ws, p)


@router.patch("/projects/{pid}")
def patch_project(pid: str, body: ProjectPatch, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    p = _own(ws, m.Project, pid)
    data = body.model_dump(exclude_unset=True)
    if "status_manual" in data:
        _correct(ws, "project_status", "project", p.id, {"status_manual": p.status_manual}, {"status_manual": data["status_manual"]})
        p.status_manual = None if data["status_manual"] == "auto" else data["status_manual"]
    for k in ("name", "description", "keywords", "color", "archived"):
        if k in data and data[k] is not None:
            setattr(p, k, data[k])
    ws.db.commit()
    return _project_summary(ws, p)


@router.get("/projects/{pid}")
def project(pid: str, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    p = _own(ws, m.Project, pid)
    db = ws.db
    out = _project_summary(ws, p)
    out["tasks"] = [task_dict(db, t) for t in db.scalars(select(m.Task).where(m.Task.user_id == ws.user_id, m.Task.project_id == pid, m.Task.status != "dismissed").order_by(m.Task.due_at.asc().nullslast()))]
    out["commitments"] = [commitment_dict(db, c) for c in db.scalars(select(m.Commitment).where(m.Commitment.user_id == ws.user_id, m.Commitment.project_id == pid).order_by(m.Commitment.detected_at.desc()))]
    out["decision_count"] = out["decisions"]
    out["decisions"] = [decision_dict(db, d) for d in db.scalars(select(m.Decision).where(m.Decision.user_id == ws.user_id, m.Decision.project_id == pid).order_by(m.Decision.decided_at.desc()))]
    out["emails"] = [email_dict(db, e) for e in db.scalars(select(m.Email).where(m.Email.user_id == ws.user_id, m.Email.project_id == pid, m.Email.sent_at <= ws.now()).order_by(m.Email.sent_at.desc()).limit(30))]
    out["meetings"] = [event_dict(db, e) for e in db.scalars(select(m.CalendarEvent).where(m.CalendarEvent.user_id == ws.user_id, m.CalendarEvent.project_id == pid).order_by(m.CalendarEvent.start_at.desc()).limit(30))]
    out["documents"] = [document_dict(db, d) for d in db.scalars(select(m.Document).where(m.Document.user_id == ws.user_id, m.Document.project_id == pid))]
    out["notes"] = [note_dict(db, n) for n in db.scalars(select(m.Note).where(m.Note.user_id == ws.user_id, m.Note.project_id == pid))]
    out["facts"] = [{"attribute": r.attribute, "value": r.value, "content": r.content, "status": r.status, "valid_from": iso(r.valid_from),
                     "valid_to": iso(r.valid_to), "source": {"type": r.source_type, "id": r.source_id, "span": r.evidence_span}}
                    for r in db.scalars(select(m.Memory).where(m.Memory.user_id == ws.user_id, m.Memory.subject_type == "project", m.Memory.subject_id == pid,
                                                                m.Memory.kind == "semantic", m.Memory.status != "archived").order_by(m.Memory.attribute, m.Memory.valid_from))]
    out["timeline"] = [{"occurred_at": iso(t.occurred_at), "kind": t.kind, "title": t.title, "ref": {"type": t.ref_type, "id": t.ref_id}}
                       for t in db.scalars(select(m.TimelineEvent).where(m.TimelineEvent.user_id == ws.user_id, m.TimelineEvent.project_id == pid, m.TimelineEvent.occurred_at <= ws.now())
                                           .order_by(m.TimelineEvent.occurred_at.desc()).limit(40))]
    return out


# ------------------------------------------------------------------------------------- commitments


@router.get("/commitments")
def commitments(status: str | None = None, person_id: str | None = None, project_id: str | None = None, direction: str | None = None,
                kind: str | None = None, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    q = select(m.Commitment).where(m.Commitment.user_id == ws.user_id, m.Commitment.detected_at <= ws.now())
    if status:
        q = q.where(m.Commitment.status.in_(status.split(",")))
    if person_id:
        q = q.where(or_(m.Commitment.actor_person_id == person_id, m.Commitment.recipient_person_id == person_id))
    if project_id:
        q = q.where(m.Commitment.project_id == project_id)
    if kind:
        q = q.where(m.Commitment.kind.in_(kind.split(",")))
    if direction == "mine":
        q = q.where(m.Commitment.actor_person_id == ws.self_person_id)
    elif direction == "owed_to_me":
        q = q.where(or_(m.Commitment.actor_person_id != ws.self_person_id, m.Commitment.actor_person_id.is_(None)))
    rows = list(ws.db.scalars(q.order_by(m.Commitment.detected_at.desc()).limit(500)))
    counts = dict(ws.db.execute(select(m.Commitment.status, func.count()).where(m.Commitment.user_id == ws.user_id,
                                                                                 m.Commitment.detected_at <= ws.now()).group_by(m.Commitment.status)).all())
    return {"now": ws.now().isoformat(), "counts": counts, "items": [commitment_dict(ws.db, c) for c in rows]}


@router.get("/commitments/{cid}")
def commitment(cid: str, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    c = _own(ws, m.Commitment, cid)
    db = ws.db
    d = commitment_dict(db, c)
    d["evidence"] = [{"role": e.role, "source_type": e.source_type, "source_id": e.source_id, "span": e.span, "observed_at": iso(e.observed_at),
                      "confidence": e.confidence, "location": e.location}
                     for e in db.scalars(select(m.Evidence).where(m.Evidence.subject_type == "commitment", m.Evidence.subject_id == cid).order_by(m.Evidence.created_at))]
    d["due_history"] = [{"old_due_at": iso(x.old_due_at), "new_due_at": iso(x.new_due_at), "source_type": x.source_type, "source_id": x.source_id,
                         "span": x.evidence_span, "observed_at": iso(x.observed_at)}
                        for x in db.scalars(select(m.CommitmentDueChange).where(m.CommitmentDueChange.commitment_id == cid).order_by(m.CommitmentDueChange.observed_at))]
    d["candidates"] = [{"id": f.id, "source_type": f.source_type, "source_id": f.source_id, "score": f.score, "signals": f.signals, "outcome": f.outcome}
                       for f in db.scalars(select(m.FulfillmentCandidate).where(m.FulfillmentCandidate.commitment_id == cid).order_by(m.FulfillmentCandidate.score.desc()))]
    deps = list(db.scalars(select(m.Relationship).where(m.Relationship.rel_type == "DEPENDS_ON", or_(m.Relationship.src_id == cid, m.Relationship.dst_id == cid))))
    dep_list = []
    for r in deps:
        other_id = r.dst_id if r.src_id == cid else r.src_id
        other = db.get(m.Commitment, other_id)
        dep_list.append({"relation": "depends_on" if r.src_id == cid else "required_by", "id": other_id,
                         "description": other.description if other else None, "status": other.status if other else None,
                         "depends_on" if r.src_id == cid else "required_by": other_id})
    d["dependencies"] = dep_list
    return d


class CommitmentPatch(BaseModel):
    status: str | None = Field(default=None, pattern="^(OPEN|FULFILLED|OVERDUE|CANCELLED|UNCERTAIN|REJECTED)$")
    due_at: datetime | None = None
    actor_person_id: str | None = None
    action: str | None = Field(default=None, max_length=100)
    object: str | None = Field(default=None, max_length=500)
    project_id: str | None = None


@router.patch("/commitments/{cid}")
def patch_commitment(cid: str, body: CommitmentPatch, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    """User correction. REJECTED = 'this is not a commitment' (kept as a tombstone so it is not re-extracted)."""
    c = _own(ws, m.Commitment, cid)
    before = {"status": c.status, "due_at": iso(c.due_at), "actor_person_id": c.actor_person_id, "action": c.action, "object": c.object,
              "project_id": c.project_id}
    data = body.model_dump(exclude_unset=True)
    if data.get("actor_person_id"):
        _own(ws, m.Person, data["actor_person_id"])
    _check_project(ws, data.get("project_id"))
    for k, v in data.items():
        setattr(c, k, v)
    if "status" in data:
        c.user_confirmed = True
        if data["status"] in ("FULFILLED", "CANCELLED"):
            c.resolved_at = ws.now()
    c.user_modified = True
    _correct(ws, "commitment", "commitment", c.id, before, {k: (iso(v) if isinstance(v, datetime) else v) for k, v in data.items()})
    ws.db.commit()
    return commitment_dict(ws.db, c)


class CandidateDecision(BaseModel):
    accept: bool


@router.post("/commitments/{cid}/candidates/{fid}")
def decide_candidate(cid: str, fid: str, body: CandidateDecision, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    c = _own(ws, m.Commitment, cid)
    f = _own(ws, m.FulfillmentCandidate, fid)
    if f.commitment_id != c.id:
        raise HTTPException(404, "not found")
    if body.accept:
        f.outcome = "fulfilled"
        c.status, c.user_confirmed, c.resolved_at = "FULFILLED", True, ws.now()
        c.resolution_source_type, c.resolution_source_id = f.source_type, f.source_id
        c.resolution_reason = f"Confirmed by you ({f.score:.0%} match)"
        ws.db.add(m.Evidence(user_id=ws.user_id, subject_type="commitment", subject_id=c.id, source_type=f.source_type, source_id=f.source_id,
                             span="Confirmed by user", observed_at=ws.now(), confidence=1.0, role="fulfillment"))
    else:
        f.outcome = "rejected"
        if c.resolution_source_id == f.source_id:
            c.resolution_source_id = c.resolution_source_type = c.resolution_reason = None
            c.resolution_confidence = None
    _correct(ws, "fulfillment_candidate", "commitment", c.id, {}, {"candidate": fid, "accept": body.accept})
    ws.db.commit()
    return commitment_dict(ws.db, c)


# ------------------------------------------------------------------------------------- decisions


@router.get("/decisions")
def decisions(project_id: str | None = None, status: str | None = None, topic: str | None = None, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    q = select(m.Decision).where(m.Decision.user_id == ws.user_id, m.Decision.decided_at <= ws.now())
    if project_id:
        q = q.where(m.Decision.project_id == project_id)
    if status:
        q = q.where(m.Decision.status == status)
    if topic:
        q = q.where(m.Decision.topic.ilike(f"%{topic}%"))
    rows = list(ws.db.scalars(q.order_by(m.Decision.decided_at.desc())))
    out = []
    for d in rows:
        dd = decision_dict(ws.db, d)
        dd["reaffirmed"] = [{"source_type": e.source_type, "source_id": e.source_id, "span": e.span, "observed_at": iso(e.observed_at)}
                            for e in ws.db.scalars(select(m.Evidence).where(m.Evidence.subject_id == d.id, m.Evidence.role == "reaffirmed"))
                            if e.source_id != d.source_id]
        out.append(dd)
    return {"items": out}


class DecisionPatch(BaseModel):
    status: str | None = Field(default=None, pattern="^(active|superseded|rejected)$")
    topic: str | None = None
    chosen: str | None = None


@router.patch("/decisions/{did}")
def patch_decision(did: str, body: DecisionPatch, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    d = _own(ws, m.Decision, did)
    before = {"status": d.status, "topic": d.topic, "chosen": d.chosen}
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(d, k, v)
    d.user_confirmed = True
    _correct(ws, "decision", "decision", d.id, before, body.model_dump(exclude_unset=True))
    ws.db.commit()
    return decision_dict(ws.db, d)


# ------------------------------------------------------------------------------------- inferences


@router.get("/inferences")
def inferences(status: str = "pending", ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    rows = list(ws.db.scalars(select(m.Inference).where(m.Inference.user_id == ws.user_id, m.Inference.status == status)
                              .order_by(m.Inference.confidence.desc()).limit(200)))
    out = []
    for i in rows:
        label = None
        if i.subject_type == "email":
            e = ws.db.get(m.Email, i.subject_id)
            label = e.subject if e else None
        elif i.subject_type == "event":
            ev = ws.db.get(m.CalendarEvent, i.subject_id)
            label = ev.title if ev else None
        elif i.subject_type in ("document", "note"):
            x = ws.db.get(m.Document, i.subject_id) if i.subject_type == "document" else ws.db.get(m.Note, i.subject_id)
            label = x.title if x else None
        out.append({"id": i.id, "kind": i.kind, "subject_type": i.subject_type, "subject_id": i.subject_id, "subject_label": label,
                    "value_id": i.value_id, "value_label": i.value_label, "confidence": i.confidence, "reasons": i.reasons, "status": i.status})
    return {"items": out}


class InferenceDecision(BaseModel):
    action: str = Field(pattern="^(confirm|change|reject)$")
    project_id: str | None = None  # for "change"
    apply_to_thread: bool = True


@router.post("/inferences/{iid}")
def decide_inference(iid: str, body: InferenceDecision, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    i = _own(ws, m.Inference, iid)
    before = {"value_id": i.value_id, "status": i.status}
    target = i.value_id if body.action == "confirm" else (body.project_id if body.action == "change" else None)
    if body.action == "change":
        if not target:
            raise HTTPException(422, "project_id required")
        p = _own(ws, m.Project, target)
        i.value_id, i.value_label = p.id, p.name
    i.status = {"confirm": "confirmed", "change": "changed", "reject": "rejected"}[body.action]
    content_models: dict[str, m.ContentModel] = {"email": m.Email, "event": m.CalendarEvent, "document": m.Document, "note": m.Note}
    model = content_models.get(i.subject_type)
    # Session.get on a union of model classes is typed as returning Base
    row = cast("m.ContentRow | None", ws.db.get(model, i.subject_id)) if model else None
    rule_key = {"document": f"document:{i.subject_id}", "note": f"note:{i.subject_id}"}.get(i.subject_type)
    if i.subject_type == "event" and isinstance(row, m.CalendarEvent):
        from app.extraction.text import normalize_subject

        rule_key = f"event_title:{normalize_subject(row.title).lower()}"
    if row is not None:
        row.project_id = target
        from app.retrieval.indexer import set_chunk_project

        set_chunk_project(ws.db, i.subject_type, i.subject_id, target)
        if i.subject_type == "email" and isinstance(row, m.Email) and row.thread_id and body.apply_to_thread:
            rule_key = f"thread:{row.thread_id}"
            t = ws.db.get(m.EmailThread, row.thread_id)
            if t:
                t.project_id = target
            for e in ws.db.scalars(select(m.Email).where(m.Email.thread_id == row.thread_id)):
                e.project_id = target
                set_chunk_project(ws.db, "email", e.id, target)
        for c in ws.db.scalars(select(m.Commitment).where(m.Commitment.source_id == i.subject_id)):
            c.project_id = target
        # graph: replace inferred BELONGS_TO edge
        for r in ws.db.scalars(select(m.Relationship).where(m.Relationship.user_id == ws.user_id, m.Relationship.src_id == i.subject_id,
                                                            m.Relationship.rel_type == "BELONGS_TO", m.Relationship.dst_type == "project")):
            if r.dst_id != target:
                r.status, r.origin = "rejected", "user"
        if target:
            ws.graph.add_edge((i.subject_type, i.subject_id), "BELONGS_TO", ("project", target), origin="user", confidence=1.0)
    _correct(ws, "project_association", i.subject_type, i.subject_id, before, {"project_id": target, "action": body.action}, rule_key)
    ws.db.commit()
    return {"ok": True, "status": i.status, "project_id": target}
