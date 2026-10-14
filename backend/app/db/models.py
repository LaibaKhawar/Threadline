"""Relational schema.

Layers:
  identity     users, sessions, settings
  sources      integrations, credentials, sync state, source items (raw synced objects)
  content      emails/threads, calendar events, documents, notes, chunks (unstructured memory)
  structured   people, organizations, projects, topics, tasks, commitments, decisions
  graph        relationships (temporal, provenance-bearing edges between any two nodes)
  memory       memories (semantic/episodic/procedural), evidence, inferences, corrections, timeline
  agent        conversations, runs, steps, tool executions, action proposals
  ops          insights, notifications, LLM calls, audit log, jobs, domain events, evaluations
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypeAlias

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    Computed,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, UserOwned

EMBED_DIM = 384
JSONType = JSON().with_variant(JSONB(), "postgresql")

# ----------------------------------------------------------------------------------------- identity


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="user")  # user | admin
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class Session(IdMixin, Base):
    __tablename__ = "sessions"
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime]
    user_agent: Mapped[str | None] = mapped_column(String(300))


class UserSettings(Base):
    __tablename__ = "user_settings"
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    ai_mode: Mapped[str] = mapped_column(String(10), default="LOCAL")  # LOCAL | HYBRID | CLOUD
    reasoning_model: Mapped[str | None] = mapped_column(String(120))
    extraction_model: Mapped[str | None] = mapped_column(String(120))
    llm_extraction_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    cloud_allowed_operations: Mapped[list[str]] = mapped_column(JSONType, default=list)  # HYBRID allow-list
    auto_create_tasks: Mapped[bool] = mapped_column(Boolean, default=False)
    briefing_config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    notification_prefs: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    procedural_prefs: Mapped[list[str]] = mapped_column(JSONType, default=list)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    self_person_id: Mapped[str | None] = mapped_column(String(36))
    self_emails: Mapped[list[str]] = mapped_column(JSONType, default=list)
    clock_override: Mapped[datetime | None]  # demo workspaces pin "now" so the story is reproducible
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    telemetry_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)


# ------------------------------------------------------------------------------------------ sources


class Integration(IdMixin, TimestampMixin, UserOwned, Base):
    __tablename__ = "integrations"
    kind: Mapped[str] = mapped_column(String(40))  # local_files | email_files | ics | demo | gmail | gcal
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="connected")  # connected|error|revoked|syncing
    config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    # Per-source privacy controls (enforced by app.privacy.policy).
    store_locally: Mapped[bool] = mapped_column(Boolean, default=True)
    local_ai_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    cloud_ai_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    last_sync_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(Text)


class Credential(IdMixin, TimestampMixin, Base):
    __tablename__ = "credentials"
    integration_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("integrations.id", ondelete="CASCADE"), unique=True
    )
    ciphertext: Mapped[str] = mapped_column(Text)  # Fernet-encrypted JSON, never logged or returned
    expires_at: Mapped[datetime | None]


class SyncState(IdMixin, TimestampMixin, Base):
    __tablename__ = "sync_states"
    integration_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("integrations.id", ondelete="CASCADE"), unique=True
    )
    cursor: Mapped[str | None] = mapped_column(Text)  # incremental token (Gmail historyId, syncToken…)
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    last_started_at: Mapped[datetime | None]
    last_completed_at: Mapped[datetime | None]
    items_created: Mapped[int] = mapped_column(Integer, default=0)
    items_updated: Mapped[int] = mapped_column(Integer, default=0)
    items_deleted: Mapped[int] = mapped_column(Integer, default=0)
    items_unchanged: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    rate_limit_remaining: Mapped[int | None] = mapped_column(Integer)
    rate_limit_reset_at: Mapped[datetime | None]


class SourceItem(IdMixin, TimestampMixin, UserOwned, Base):
    """One external object (message, event, file) with deterministic identity for idempotent sync."""

    __tablename__ = "source_items"
    __table_args__ = (UniqueConstraint("user_id", "integration_id", "external_id", name="uq_source_item_ext"),)
    integration_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("integrations.id", ondelete="CASCADE"), index=True
    )
    external_id: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(20))  # email | event | document | note
    content_hash: Mapped[str] = mapped_column(String(64))
    external_updated_at: Mapped[datetime | None]
    synced_at: Mapped[datetime] = mapped_column(server_default=func.now())
    deleted_at: Mapped[datetime | None]
    processing_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|done|error
    processing_error: Mapped[str | None] = mapped_column(Text)


# ------------------------------------------------------------------------------------------ content


class EmailThread(IdMixin, TimestampMixin, UserOwned, Base):
    __tablename__ = "email_threads"
    thread_key: Mapped[str] = mapped_column(String(500))
    subject: Mapped[str] = mapped_column(String(500))
    first_at: Mapped[datetime | None]
    last_at: Mapped[datetime | None]
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id", ondelete="SET NULL"))
    summary: Mapped[str | None] = mapped_column(Text)
    awaiting: Mapped[str | None] = mapped_column(String(20))  # me | them | None (derived)
    __table_args__ = (UniqueConstraint("user_id", "thread_key", name="uq_thread_key"),)


class Email(IdMixin, TimestampMixin, UserOwned, Base):
    __tablename__ = "emails"
    source_item_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_items.id", ondelete="CASCADE"), index=True
    )
    thread_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("email_threads.id", ondelete="SET NULL"), index=True
    )
    message_id: Mapped[str] = mapped_column(String(500))
    in_reply_to: Mapped[str | None] = mapped_column(String(500))
    references: Mapped[list[str]] = mapped_column(JSONType, default=list)
    from_addr: Mapped[str] = mapped_column(String(320), index=True)
    from_name: Mapped[str | None] = mapped_column(String(200))
    to_addrs: Mapped[list[dict[str, str]]] = mapped_column(JSONType, default=list)
    cc_addrs: Mapped[list[dict[str, str]]] = mapped_column(JSONType, default=list)
    subject: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(index=True)
    direction: Mapped[str] = mapped_column(String(10), default="inbound")  # inbound | outbound
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    sender_person_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("people.id", ondelete="SET NULL"), index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    labels: Mapped[list[str]] = mapped_column(JSONType, default=list)


class CalendarEvent(IdMixin, TimestampMixin, UserOwned, Base):
    __tablename__ = "calendar_events"
    source_item_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_items.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(500))
    start_at: Mapped[datetime] = mapped_column(index=True)
    end_at: Mapped[datetime]
    attendees: Mapped[list[dict[str, str]]] = mapped_column(JSONType, default=list)
    organizer: Mapped[str | None] = mapped_column(String(320))
    notes: Mapped[str | None] = mapped_column(Text)  # meeting notes / transcript summary
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="confirmed")


class EventParticipant(Base):
    __tablename__ = "event_participants"
    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("calendar_events.id", ondelete="CASCADE"), primary_key=True
    )
    person_id: Mapped[str] = mapped_column(String(36), ForeignKey("people.id", ondelete="CASCADE"), primary_key=True)
    response: Mapped[str | None] = mapped_column(String(20))


class Document(IdMixin, TimestampMixin, UserOwned, Base):
    __tablename__ = "documents"
    source_item_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_items.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    original_filename: Mapped[str] = mapped_column(String(300))
    storage_name: Mapped[str] = mapped_column(String(100))  # generated; never a user-supplied path
    mime_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    page_count: Mapped[int | None] = mapped_column(Integer)
    doc_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|processing|ready|error
    error: Mapped[str | None] = mapped_column(Text)
    author_person_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("people.id", ondelete="SET NULL"))
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    authored_at: Mapped[datetime | None]


class Note(IdMixin, TimestampMixin, UserOwned, Base):
    __tablename__ = "notes"
    source_item_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_items.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")  # user-written markdown; AI never edits this
    ai_annotations: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)  # kept separate
    tags: Mapped[list[str]] = mapped_column(JSONType, default=list)
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id", ondelete="SET NULL"))
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)


class Chunk(IdMixin, UserOwned, Base):
    """Retrieval unit for every unstructured source, with location for provenance."""

    __tablename__ = "chunks"
    owner_type: Mapped[str] = mapped_column(String(20))  # email | document | note | event
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    integration_id: Mapped[str | None] = mapped_column(String(36), index=True)  # privacy filtering
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(500))
    page: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(500))
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer, default=0)
    occurred_at: Mapped[datetime | None] = mapped_column(index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), index=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))
    embedding_model: Mapped[str | None] = mapped_column(String(120))
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', coalesce(title, '') || ' ' || text)", persisted=True),
    )
    __table_args__ = (
        Index("ix_chunks_owner", "owner_type", "owner_id"),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


# --------------------------------------------------------------------------------------- structured


class Organization(IdMixin, TimestampMixin, UserOwned, Base):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str | None] = mapped_column(String(200))
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_org_name"),)


class Person(IdMixin, TimestampMixin, UserOwned, Base):
    __tablename__ = "people"
    display_name: Mapped[str] = mapped_column(String(200))
    primary_email: Mapped[str | None] = mapped_column(String(320), index=True)
    title: Mapped[str | None] = mapped_column(String(200))
    organization_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="SET NULL")
    )
    is_self: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    merged_into_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("people.id", ondelete="SET NULL"))
    last_interaction_at: Mapped[datetime | None]
    created_by: Mapped[str] = mapped_column(String(20), default="extraction")  # extraction|user|contacts


class PersonAlias(IdMixin, UserOwned, Base):
    __tablename__ = "person_aliases"
    person_id: Mapped[str] = mapped_column(String(36), ForeignKey("people.id", ondelete="CASCADE"), index=True)
    alias: Mapped[str] = mapped_column(String(320))
    alias_norm: Mapped[str] = mapped_column(String(320), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # name | email
    source_type: Mapped[str | None] = mapped_column(String(20))
    source_id: Mapped[str | None] = mapped_column(String(36))
    __table_args__ = (UniqueConstraint("person_id", "alias_norm", "kind", name="uq_person_alias"),)


class MergeCandidate(IdMixin, TimestampMixin, UserOwned, Base):
    """Uncertain identity matches are queued for the user instead of being merged automatically."""

    __tablename__ = "merge_candidates"
    person_a_id: Mapped[str] = mapped_column(String(36), ForeignKey("people.id", ondelete="CASCADE"))
    person_b_id: Mapped[str] = mapped_column(String(36), ForeignKey("people.id", ondelete="CASCADE"))
    score: Mapped[float] = mapped_column(Float)
    reasons: Mapped[list[str]] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|merged|rejected


class Project(IdMixin, TimestampMixin, UserOwned, Base):
    __tablename__ = "projects"
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[list[str]] = mapped_column(JSONType, default=list)
    status_manual: Mapped[str | None] = mapped_column(String(30))  # user override of the AI status
    color: Mapped[str | None] = mapped_column(String(20))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_project_name"),)


class ProjectMember(Base):
    __tablename__ = "project_members"
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    person_id: Mapped[str] = mapped_column(String(36), ForeignKey("people.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str | None] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(20), default="inferred")  # inferred | user


class Topic(IdMixin, UserOwned, Base):
    __tablename__ = "topics"
    name: Mapped[str] = mapped_column(String(200))
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_topic_name"),)


class Task(IdMixin, TimestampMixin, UserOwned, Base):
    __tablename__ = "tasks"
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    owner_person_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("people.id", ondelete="SET NULL"))
    # suggested -> active -> done ; suggested -> dismissed ; active <-> blocked
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    priority: Mapped[str] = mapped_column(String(10), default="medium")  # low|medium|high|urgent
    due_at: Mapped[datetime | None]
    blocked_by_person_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("people.id", ondelete="SET NULL"))
    blocked_reason: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str | None] = mapped_column(String(20))
    source_id: Mapped[str | None] = mapped_column(String(36), index=True)
    evidence_span: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    manually_created: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_suggested: Mapped[bool] = mapped_column(Boolean, default=False)
    user_modified: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None]
    dedupe_key: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("user_id", "dedupe_key", name="uq_task_dedupe"),)


class Commitment(IdMixin, TimestampMixin, UserOwned, Base):
    __tablename__ = "commitments"
    kind: Mapped[str] = mapped_column(String(20), default="commitment")  # commitment | request | intention
    actor_person_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("people.id", ondelete="SET NULL"), index=True)
    recipient_person_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("people.id", ondelete="SET NULL"))
    actor_text: Mapped[str | None] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(100))
    object: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[str] = mapped_column(String(36), index=True)
    evidence_span: Mapped[str] = mapped_column(Text)
    span_start: Mapped[int | None] = mapped_column(Integer)
    span_end: Mapped[int | None] = mapped_column(Integer)
    detected_at: Mapped[datetime]
    due_at: Mapped[datetime | None]
    due_text: Mapped[str | None] = mapped_column(String(100))
    # OPEN | FULFILLED | OVERDUE | CANCELLED | UNCERTAIN
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    confidence: Mapped[float] = mapped_column(Float)
    extractor: Mapped[str] = mapped_column(String(20), default="rules")  # rules | llm | user
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    resolution_source_type: Mapped[str | None] = mapped_column(String(20))
    resolution_source_id: Mapped[str | None] = mapped_column(String(36))
    resolution_confidence: Mapped[float | None] = mapped_column(Float)
    resolution_reason: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None]
    user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    user_modified: Mapped[bool] = mapped_column(Boolean, default=False)
    dedupe_key: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("user_id", "dedupe_key", name="uq_commitment_dedupe"),)


class CommitmentDueChange(IdMixin, UserOwned, Base):
    """Due-date history: a moved deadline supersedes the old one; the old one is kept."""

    __tablename__ = "commitment_due_changes"
    commitment_id: Mapped[str] = mapped_column(String(36), ForeignKey("commitments.id", ondelete="CASCADE"), index=True)
    old_due_at: Mapped[datetime | None]
    new_due_at: Mapped[datetime | None]
    source_type: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[str] = mapped_column(String(36))
    evidence_span: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime]


class FulfillmentCandidate(IdMixin, TimestampMixin, UserOwned, Base):
    """Every candidate match considered by commitment resolution, kept for inspection."""

    __tablename__ = "fulfillment_candidates"
    commitment_id: Mapped[str] = mapped_column(String(36), ForeignKey("commitments.id", ondelete="CASCADE"), index=True)
    source_type: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[str] = mapped_column(String(36), index=True)
    score: Mapped[float] = mapped_column(Float)
    signals: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    outcome: Mapped[str] = mapped_column(String(20))  # fulfilled | cancelled | candidate | rejected
    __table_args__ = (UniqueConstraint("commitment_id", "source_id", name="uq_fulfillment_pair"),)


class Decision(IdMixin, TimestampMixin, UserOwned, Base):
    __tablename__ = "decisions"
    topic: Mapped[str] = mapped_column(String(200), index=True)
    chosen: Mapped[str] = mapped_column(String(300))
    rejected: Mapped[list[str]] = mapped_column(JSONType, default=list)
    statement: Mapped[str] = mapped_column(Text)
    decided_at: Mapped[datetime]
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    source_type: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[str] = mapped_column(String(36), index=True)
    evidence_span: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | superseded | rejected
    superseded_by_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("decisions.id", ondelete="SET NULL"))
    participants: Mapped[list[str]] = mapped_column(JSONType, default=list)  # person ids
    user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    dedupe_key: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("user_id", "dedupe_key", name="uq_decision_dedupe"),)


# -------------------------------------------------------------------------------------------- graph


class Relationship(IdMixin, UserOwned, Base):
    """Temporal, provenance-bearing edge. Nodes are (type, id) references into the tables above.

    History is never overwritten: a changed fact closes the old edge (valid_to, status=superseded)
    and opens a new one.
    """

    __tablename__ = "relationships"
    src_type: Mapped[str] = mapped_column(String(20))
    src_id: Mapped[str] = mapped_column(String(36))
    rel_type: Mapped[str] = mapped_column(String(40), index=True)
    dst_type: Mapped[str] = mapped_column(String(20))
    dst_id: Mapped[str] = mapped_column(String(36))
    valid_from: Mapped[datetime | None]
    valid_to: Mapped[datetime | None]
    observed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|superseded|rejected
    superseded_by_id: Mapped[str | None] = mapped_column(String(36))
    source_type: Mapped[str | None] = mapped_column(String(20))
    source_id: Mapped[str | None] = mapped_column(String(36), index=True)
    evidence_span: Mapped[str | None] = mapped_column(Text)
    properties: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    origin: Mapped[str] = mapped_column(String(20), default="extraction")  # extraction|structural|user
    __table_args__ = (
        Index("ix_rel_src", "user_id", "src_type", "src_id"),
        Index("ix_rel_dst", "user_id", "dst_type", "dst_id"),
        UniqueConstraint(
            "user_id", "src_type", "src_id", "rel_type", "dst_type", "dst_id", "source_id",
            name="uq_relationship_fact",
        ),
    )


# ------------------------------------------------------------------------------------------- memory


class Evidence(IdMixin, UserOwned, Base):
    """Provenance for any derived claim: what source, where in it, which words, how confident."""

    __tablename__ = "evidence"
    subject_type: Mapped[str] = mapped_column(String(30))
    subject_id: Mapped[str] = mapped_column(String(36))
    source_type: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[str] = mapped_column(String(36), index=True)
    location: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)  # page/section/offsets
    span: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime | None]
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    role: Mapped[str] = mapped_column(String(30), default="source")  # source | fulfillment | change
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    __table_args__ = (Index("ix_evidence_subject", "subject_type", "subject_id"),)


class Memory(IdMixin, TimestampMixin, UserOwned, Base):
    __tablename__ = "memories"
    kind: Mapped[str] = mapped_column(String(20))  # semantic | episodic | procedural
    content: Mapped[str] = mapped_column(Text)
    subject_type: Mapped[str | None] = mapped_column(String(20))
    subject_id: Mapped[str | None] = mapped_column(String(36), index=True)
    attribute: Mapped[str | None] = mapped_column(String(100))  # e.g. "deadline", "works_at"
    value: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|superseded|archived
    superseded_by_id: Mapped[str | None] = mapped_column(String(36))
    valid_from: Mapped[datetime | None]
    valid_to: Mapped[datetime | None]
    observed_at: Mapped[datetime | None]
    source_type: Mapped[str | None] = mapped_column(String(20))
    source_id: Mapped[str | None] = mapped_column(String(36), index=True)
    evidence_span: Mapped[str | None] = mapped_column(Text)
    reinforcement_count: Mapped[int] = mapped_column(Integer, default=1)
    dedupe_key: Mapped[str] = mapped_column(String(64))
    origin: Mapped[str] = mapped_column(String(20), default="extraction")  # extraction | user
    __table_args__ = (UniqueConstraint("user_id", "dedupe_key", name="uq_memory_dedupe"),)


class Inference(IdMixin, TimestampMixin, UserOwned, Base):
    """An inspectable AI inference (e.g. project association) awaiting or carrying user feedback."""

    __tablename__ = "inferences"
    kind: Mapped[str] = mapped_column(String(40))  # project_association | person_org | ...
    subject_type: Mapped[str] = mapped_column(String(20))
    subject_id: Mapped[str] = mapped_column(String(36), index=True)
    value_id: Mapped[str | None] = mapped_column(String(36))
    value_label: Mapped[str | None] = mapped_column(String(300))
    confidence: Mapped[float] = mapped_column(Float)
    reasons: Mapped[list[str]] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|confirmed|rejected|changed|auto
    __table_args__ = (UniqueConstraint("user_id", "kind", "subject_type", "subject_id", name="uq_inference"),)


class Correction(IdMixin, UserOwned, Base):
    """User corrections. These outrank model inference on every subsequent extraction pass."""

    __tablename__ = "corrections"
    kind: Mapped[str] = mapped_column(String(40))
    target_type: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[str] = mapped_column(String(36))
    before: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    after: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    rule_key: Mapped[str | None] = mapped_column(String(300), index=True)  # e.g. "project:subject:atlas"
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class TimelineEvent(IdMixin, UserOwned, Base):
    __tablename__ = "timeline_events"
    occurred_at: Mapped[datetime] = mapped_column(index=True)
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(500))
    detail: Mapped[str | None] = mapped_column(Text)
    ref_type: Mapped[str | None] = mapped_column(String(20))
    ref_id: Mapped[str | None] = mapped_column(String(36), index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), index=True)
    person_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)
    dedupe_key: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("user_id", "dedupe_key", name="uq_timeline_dedupe"),)


# -------------------------------------------------------------------------------------------- agent


class Conversation(IdMixin, TimestampMixin, UserOwned, Base):
    __tablename__ = "conversations"
    title: Mapped[str] = mapped_column(String(300))
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id", ondelete="SET NULL"))


class AgentRun(IdMixin, TimestampMixin, UserOwned, Base):
    __tablename__ = "agent_runs"
    conversation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    question: Mapped[str] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|completed|failed
    answer: Mapped[str | None] = mapped_column(Text)
    answer_mode: Mapped[str | None] = mapped_column(String(20))  # llm | extractive
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    verification: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    provider: Mapped[str | None] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(120))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text)
    feedback: Mapped[str | None] = mapped_column(String(20))


class AgentStep(IdMixin, Base):
    __tablename__ = "agent_steps"
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    phase: Mapped[str] = mapped_column(String(20))  # plan|execute|observe|revise|verify|answer
    summary: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ToolExecution(IdMixin, Base):
    __tablename__ = "tool_executions"
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    tool: Mapped[str] = mapped_column(String(60))
    args: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    access: Mapped[str] = mapped_column(String(10))  # read | write
    status: Mapped[str] = mapped_column(String(20))  # ok | error | denied | proposed
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ActionProposal(IdMixin, TimestampMixin, UserOwned, Base):
    """Human-in-the-loop gate: write actions exist only as proposals until the user approves."""

    __tablename__ = "action_proposals"
    run_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("agent_runs.id", ondelete="SET NULL"))
    tool: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|approved|rejected|executed|failed
    decided_at: Mapped[datetime | None]
    result: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


# ---------------------------------------------------------------------------------------------- ops


class Insight(IdMixin, TimestampMixin, UserOwned, Base):
    """Output of proactive intelligence: follow-ups, overdue items, stalled projects, conflicts."""

    __tablename__ = "insights"
    kind: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(500))
    explanation: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    ref_type: Mapped[str | None] = mapped_column(String(20))
    ref_id: Mapped[str | None] = mapped_column(String(36))
    project_id: Mapped[str | None] = mapped_column(String(36))
    person_id: Mapped[str | None] = mapped_column(String(36))
    confidence: Mapped[float] = mapped_column(Float)
    importance: Mapped[float] = mapped_column(Float)
    urgency: Mapped[float] = mapped_column(Float)
    score: Mapped[float] = mapped_column(Float, index=True)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|dismissed|resolved|snoozed
    feedback: Mapped[str | None] = mapped_column(String(20))  # useful | not_useful
    suggested_action: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    dedupe_key: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("user_id", "dedupe_key", name="uq_insight_dedupe"),)


class Notification(IdMixin, UserOwned, Base):
    __tablename__ = "notifications"
    category: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    ref_type: Mapped[str | None] = mapped_column(String(20))
    ref_id: Mapped[str | None] = mapped_column(String(36))
    insight_id: Mapped[str | None] = mapped_column(String(36))
    score: Mapped[float] = mapped_column(Float, default=0.5)
    read_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    dedupe_key: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("user_id", "dedupe_key", name="uq_notification_dedupe"),)


class LLMCall(IdMixin, Base):
    __tablename__ = "llm_calls"
    user_id: Mapped[str | None] = mapped_column(String(36), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36))
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(120))
    locality: Mapped[str] = mapped_column(String(10))  # local | cloud
    operation: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    source_types: Mapped[list[str]] = mapped_column(JSONType, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)


class AuditLog(IdMixin, Base):
    __tablename__ = "audit_log"
    user_id: Mapped[str | None] = mapped_column(String(36), index=True)
    actor: Mapped[str] = mapped_column(String(20))  # user | ai | system
    action: Mapped[str] = mapped_column(String(80))
    target_type: Mapped[str | None] = mapped_column(String(30))
    target_id: Mapped[str | None] = mapped_column(String(36))
    details: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)


class Job(IdMixin, Base):
    __tablename__ = "jobs"
    user_id: Mapped[str | None] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|succeeded|failed|dead
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    progress: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class DomainEvent(IdMixin, Base):
    """Transactional outbox. Written in the same transaction as the change it describes."""

    __tablename__ = "domain_events"
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    type: Mapped[str] = mapped_column(String(60), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|processing|done|failed|dead
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    started_at: Mapped[datetime | None]
    processed_at: Mapped[datetime | None]


class EvaluationRun(IdMixin, Base):
    __tablename__ = "evaluation_runs"
    suite: Mapped[str] = mapped_column(String(60))
    config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    details: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())




# ------------------------------------------------------------------------------------- type helpers
# Content tables that are dispatched on by owner/subject type ("email", "event", "document", "note").
ContentModel: TypeAlias = type[Email] | type[CalendarEvent] | type[Document] | type[Note]
ContentRow: TypeAlias = Email | CalendarEvent | Document | Note
