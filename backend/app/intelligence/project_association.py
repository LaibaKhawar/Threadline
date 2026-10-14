"""Infer which project an item belongs to, with inspectable reasons and user override.

Signals (additive, capped at 0.99):
  explicit project name in subject/title  +0.65
  explicit project name in body           +0.40
  project keyword(s) in text              +0.15 each (max 0.30)
  participants who are project members    +0.10 each (max 0.30)
  same thread already associated          +0.45
User corrections are rules and win outright (confidence 1.0).
Assign automatically at >= 0.6; 0.35-0.6 stays a pending suggestion the user can confirm.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m

AUTO_ASSIGN = 0.6
SUGGEST = 0.35


@dataclass
class ProjectScore:
    project_id: str
    project_name: str
    score: float
    reasons: list[str] = field(default_factory=list)


def score_projects(
    db: Session,
    user_id: str,
    *,
    title: str,
    body: str,
    participant_ids: set[str],
    thread_project_id: str | None = None,
) -> list[ProjectScore]:
    projects = list(db.scalars(select(m.Project).where(m.Project.user_id == user_id, m.Project.archived.is_(False))))
    if not projects:
        return []
    members: dict[str, set[str]] = {}
    for pm in db.scalars(select(m.ProjectMember).where(m.ProjectMember.project_id.in_([p.id for p in projects]))):
        members.setdefault(pm.project_id, set()).add(pm.person_id)
    out = []
    for p in projects:
        score, reasons = 0.0, []
        name_re = re.compile(r"\b" + re.escape(p.name) + r"\b", re.IGNORECASE)
        if name_re.search(title or ""):
            score += 0.65
            reasons.append(f"title mentions “{p.name}”")
        elif name_re.search(body or ""):
            score += 0.40
            reasons.append(f"text mentions “{p.name}”")
        kw_hits = [k for k in (p.keywords or []) if k.lower() != p.name.lower()
                   and re.search(r"\b" + re.escape(k) + r"\b", f"{title}\n{body}", re.IGNORECASE)]
        if kw_hits:
            score += min(0.30, 0.15 * len(kw_hits))
            reasons.append("keywords: " + ", ".join(kw_hits[:4]))
        overlap = participant_ids & members.get(p.id, set())
        if overlap:
            score += min(0.30, 0.10 * len(overlap))
            reasons.append(f"{len(overlap)} participant(s) are project members")
        if thread_project_id == p.id:
            score += 0.45
            reasons.append("earlier messages in this thread belong to the project")
        if score > 0:
            out.append(ProjectScore(p.id, p.name, round(min(score, 0.99), 3), reasons))
    return sorted(out, key=lambda s: -s.score)


def correction_override(db: Session, user_id: str, keys: list[str]) -> str | None:
    """A user correction for this thread/sender pins the project (value_id may be None = no project)."""
    for key in keys:
        c = db.scalar(select(m.Correction).where(m.Correction.user_id == user_id, m.Correction.kind == "project_association",
                                                 m.Correction.rule_key == key).order_by(m.Correction.created_at.desc()))
        if c:
            return (c.after or {}).get("project_id") or "__none__"
    return None


def associate(
    db: Session,
    user_id: str,
    *,
    subject_type: str,
    subject_id: str,
    title: str,
    body: str,
    participant_ids: set[str],
    thread_project_id: str | None = None,
    rule_keys: list[str] | None = None,
) -> tuple[str | None, m.Inference | None]:
    """Return (project_id to assign, inference row). Never overrides a confirmed/corrected inference."""
    inf = db.scalar(select(m.Inference).where(m.Inference.user_id == user_id, m.Inference.kind == "project_association",
                                              m.Inference.subject_type == subject_type, m.Inference.subject_id == subject_id))
    if inf and inf.status in ("confirmed", "changed", "rejected"):
        return (inf.value_id if inf.status != "rejected" else None), inf
    override = correction_override(db, user_id, rule_keys or [])
    if override:
        pid = None if override == "__none__" else override
        proj = db.get(m.Project, pid) if pid else None
        inf = _upsert(db, inf, user_id, subject_type, subject_id, pid, proj.name if proj else None, 1.0,
                      ["your earlier correction for this thread/sender"], "auto")
        return pid, inf
    scores = score_projects(db, user_id, title=title, body=body, participant_ids=participant_ids,
                            thread_project_id=thread_project_id)
    if not scores or scores[0].score < SUGGEST:
        return None, inf
    top = scores[0]
    # Ambiguity guard: two projects within 0.1 of each other stay a suggestion.
    ambiguous = len(scores) > 1 and scores[1].score >= top.score - 0.1
    status = "auto" if top.score >= AUTO_ASSIGN and not ambiguous else "pending"
    reasons = top.reasons + ([f"also close: {scores[1].project_name} ({scores[1].score:.0%})"] if ambiguous else [])
    inf = _upsert(db, inf, user_id, subject_type, subject_id, top.project_id, top.project_name, top.score, reasons, status)
    return (top.project_id if status == "auto" else None), inf


def _upsert(db: Session, inf: m.Inference | None, user_id: str, subject_type: str, subject_id: str,
            value_id: str | None, label: str | None, conf: float, reasons: list[str], status: str) -> m.Inference:
    if inf is None:
        inf = m.Inference(user_id=user_id, kind="project_association", subject_type=subject_type, subject_id=subject_id,
                          value_id=value_id, value_label=label, confidence=conf, reasons=reasons, status=status)
        db.add(inf)
    else:
        inf.value_id, inf.value_label, inf.confidence, inf.reasons, inf.status = value_id, label, conf, reasons, status
    return inf
