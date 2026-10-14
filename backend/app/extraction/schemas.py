"""Typed extraction outputs. The LLM extractor must produce exactly these shapes (validated by Pydantic);
malformed output is rejected and retried, never partially trusted."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Span(BaseModel):
    start: int
    end: int
    text: str


class PersonMention(BaseModel):
    name: str
    email: str | None = None
    span: Span | None = None
    role: Literal["sender", "recipient", "cc", "mentioned", "attendee", "author", "addressee"] = "mentioned"
    confidence: float = 0.8


class OrgMention(BaseModel):
    name: str
    span: Span | None = None
    domain: str | None = None
    confidence: float = 0.7


class ProjectMention(BaseModel):
    name: str
    span: Span | None = None
    confidence: float = 0.8


class CommitmentExtraction(BaseModel):
    """Who promised (or was asked) to do what, for whom, by when, and the exact words."""

    kind: Literal["commitment", "request", "intention"] = "commitment"
    actor: str = Field(description="Person name, 'SPEAKER' for the author, or 'ADDRESSEE' for the reader")
    action: str = Field(min_length=2, max_length=60)
    object: str | None = Field(default=None, max_length=300)
    recipient: str | None = None
    due_text: str | None = None
    due_at: datetime | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    source_span: str = Field(min_length=3)
    span_start: int | None = None
    span_end: int | None = None
    depends_on_index: int | None = None  # index of an earlier commitment in the same source

    @field_validator("action")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.strip().lower()


class CompletionSignal(BaseModel):
    """Evidence that something was delivered/done (used to resolve commitments)."""

    actor: str
    action: str
    object: str | None
    source_span: str
    span_start: int
    span_end: int
    kind: Literal["completed", "cancelled", "declined"] = "completed"


class DecisionExtraction(BaseModel):
    topic: str = Field(min_length=2, max_length=100)
    chosen: str = Field(min_length=1, max_length=200)
    rejected: list[str] = Field(default_factory=list)
    reverses_previous: bool = False
    source_span: str
    span_start: int | None = None
    span_end: int | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class DeadlineChange(BaseModel):
    kind: Literal["moved", "set"] = "moved"
    subject: str
    new_due_at: datetime
    due_text: str
    source_span: str
    span_start: int
    span_end: int
    confidence: float = 0.8


class EmploymentFact(BaseModel):
    person: str
    organization: str
    title: str | None = None
    kind: Literal["joined", "left", "signature"] = "joined"
    source_span: str
    confidence: float = 0.75


class BlockerFact(BaseModel):
    blocked_item: str
    blocked_by: str
    source_span: str
    span_start: int
    span_end: int


class ExtractionResult(BaseModel):
    people: list[PersonMention] = Field(default_factory=list)
    organizations: list[OrgMention] = Field(default_factory=list)
    projects: list[ProjectMention] = Field(default_factory=list)
    dates: list[Span] = Field(default_factory=list)
    commitments: list[CommitmentExtraction] = Field(default_factory=list)
    completions: list[CompletionSignal] = Field(default_factory=list)
    decisions: list[DecisionExtraction] = Field(default_factory=list)
    deadline_changes: list[DeadlineChange] = Field(default_factory=list)
    employment: list[EmploymentFact] = Field(default_factory=list)
    blockers: list[BlockerFact] = Field(default_factory=list)
    extractor: str = "rules"


class LLMExtractionPayload(BaseModel):
    """What the LLM is asked to return (spans are verified against the source afterwards)."""

    people: list[str] = Field(default_factory=list)
    organizations: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    commitments: list[CommitmentExtraction] = Field(default_factory=list)
    decisions: list[DecisionExtraction] = Field(default_factory=list)
