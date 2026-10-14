"""Assistant, conversations, runs (with safe structured activity), and the human-in-the-loop proposals."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.runtime import AgentRuntime
from app.agent.tools import REGISTRY
from app.api.deps import rate_limit, workspace
from app.api.serialize import iso
from app.db import models as m
from app.ingestion.workspace import Workspace

router = APIRouter(prefix="/api", tags=["assistant"])


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    use_llm: bool = True


@router.post("/assistant/ask", dependencies=[Depends(rate_limit("assistant", 30))])
def ask(body: AskIn, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    out = AgentRuntime(ws.db, ws.user_id, use_llm=body.use_llm).run(body.question, conversation_id=body.conversation_id)
    run = ws.db.get(m.AgentRun, out.run_id)
    return {"run_id": out.run_id, "conversation_id": run.conversation_id if run else None, "answer": out.answer,
            "answer_mode": out.answer_mode, "citations": out.citations, "steps": out.steps, "verification": out.verification,
            "parsed": out.parsed, "proposals": out.proposals, "model": run.model if run else None, "latency_ms": run.latency_ms if run else None}


@router.get("/assistant/tools")
def tools() -> dict[str, Any]:
    return {"tools": [t.manifest() for t in REGISTRY.values()]}


@router.get("/conversations")
def conversations(ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    rows = list(ws.db.scalars(select(m.Conversation).where(m.Conversation.user_id == ws.user_id).order_by(m.Conversation.updated_at.desc()).limit(50)))
    return {"items": [{"id": c.id, "title": c.title, "updated_at": iso(c.updated_at)} for c in rows]}


@router.get("/conversations/{cid}")
def conversation(cid: str, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    c = ws.db.get(m.Conversation, cid)
    if not c or c.user_id != ws.user_id:
        raise HTTPException(404, "not found")
    runs = list(ws.db.scalars(select(m.AgentRun).where(m.AgentRun.conversation_id == cid).order_by(m.AgentRun.created_at)))
    return {"id": c.id, "title": c.title, "runs": [_run_dict(ws, r) for r in runs]}


@router.delete("/conversations/{cid}")
def delete_conversation(cid: str, ws: Workspace = Depends(workspace)) -> dict[str, bool]:
    c = ws.db.get(m.Conversation, cid)
    if not c or c.user_id != ws.user_id:
        raise HTTPException(404, "not found")
    ws.db.delete(c)
    ws.db.commit()
    return {"ok": True}


def _run_dict(ws: Workspace, r: m.AgentRun) -> dict[str, Any]:
    steps = list(ws.db.scalars(select(m.AgentStep).where(m.AgentStep.run_id == r.id).order_by(m.AgentStep.ordinal)))
    props = list(ws.db.scalars(select(m.ActionProposal).where(m.ActionProposal.run_id == r.id)))
    return {"run_id": r.id, "question": r.question, "answer": r.answer, "answer_mode": r.answer_mode, "citations": r.citations,
            "verification": r.verification, "status": r.status, "latency_ms": r.latency_ms, "model": r.model, "feedback": r.feedback,
            "created_at": iso(r.created_at), "steps": [{"phase": s.phase, "summary": s.summary, "data": s.data} for s in steps],
            "proposals": [_proposal(p) for p in props]}


@router.get("/runs/{rid}")
def run(rid: str, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    r = ws.db.get(m.AgentRun, rid)
    if not r or r.user_id != ws.user_id:
        raise HTTPException(404, "not found")
    tools = list(ws.db.scalars(select(m.ToolExecution).where(m.ToolExecution.run_id == rid)))
    calls = list(ws.db.scalars(select(m.LLMCall).where(m.LLMCall.run_id == rid)))
    d = _run_dict(ws, r)
    d["tool_executions"] = [{"tool": t.tool, "access": t.access, "status": t.status, "result_count": t.result_count,
                             "latency_ms": t.latency_ms, "error": t.error} for t in tools]
    d["llm_calls"] = [{"provider": c.provider, "model": c.model, "locality": c.locality, "input_tokens": c.input_tokens,
                       "output_tokens": c.output_tokens, "latency_ms": c.latency_ms, "cost_usd": c.cost_usd} for c in calls]
    return d


class FeedbackIn(BaseModel):
    feedback: str = Field(pattern="^(helpful|not_helpful|wrong_sources)$")


@router.post("/runs/{rid}/feedback")
def run_feedback(rid: str, body: FeedbackIn, ws: Workspace = Depends(workspace)) -> dict[str, bool]:
    r = ws.db.get(m.AgentRun, rid)
    if not r or r.user_id != ws.user_id:
        raise HTTPException(404, "not found")
    r.feedback = body.feedback
    ws.db.commit()
    return {"ok": True}


# ------------------------------------------------------------------------------------- proposals (HITL)


def _proposal(p: m.ActionProposal) -> dict[str, Any]:
    tool = REGISTRY.get(p.tool)
    return {"id": p.id, "tool": p.tool, "payload": p.payload, "reason": p.reason, "status": p.status, "result": p.result,
            "created_at": iso(p.created_at), "decided_at": iso(p.decided_at), "permission": tool.manifest() if tool else None}


@router.get("/proposals")
def proposals(status: str | None = None, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    q = select(m.ActionProposal).where(m.ActionProposal.user_id == ws.user_id)
    if status:
        q = q.where(m.ActionProposal.status == status)
    return {"items": [_proposal(p) for p in ws.db.scalars(q.order_by(m.ActionProposal.created_at.desc()).limit(100))]}


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    payload: dict[str, Any] | None = None  # edited payload (Edit -> Approve)


@router.post("/proposals/{pid}")
def decide(pid: str, body: DecisionIn, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    p = ws.db.get(m.ActionProposal, pid)
    if not p or p.user_id != ws.user_id:
        raise HTTPException(404, "not found")
    if p.status != "pending":
        raise HTTPException(409, f"proposal already {p.status}")
    if body.payload is not None:
        allowed = {"to", "to_name", "subject", "body", "title", "due_at", "project_id"}
        p.payload = {**p.payload, **{k: v for k, v in body.payload.items() if k in allowed}}
    p.decided_at = ws.now()
    if body.decision == "reject":
        p.status = "rejected"
    else:
        p.status, p.result = "approved", _execute_approved(ws, p)
        if p.result.get("executed"):
            p.status = "executed"
    ws.db.add(m.AuditLog(user_id=ws.user_id, actor="user", action=f"proposal_{body.decision}", target_type="proposal", target_id=p.id,
                         details={"tool": p.tool, "result": p.result}))
    ws.db.commit()
    return _proposal(p)


def _execute_approved(ws: Workspace, p: m.ActionProposal) -> dict[str, Any]:
    """Execute only what Threadline can do locally. External sends are not supported (read-only scopes)."""
    if p.tool == "create_task":
        pid = p.payload.get("project_id")
        if pid and (proj := ws.db.get(m.Project, pid)) is not None and proj.user_id != ws.user_id:
            return {"executed": False, "message": "project not found"}
        t = m.Task(user_id=ws.user_id, title=str(p.payload.get("title", "Untitled"))[:500], status="active", manually_created=True,
                   project_id=p.payload.get("project_id"))
        ws.db.add(t)
        ws.db.flush()
        return {"executed": True, "task_id": t.id}
    if p.tool in ("draft_email", "send_email"):
        return {"executed": False, "message": "Draft approved. Copy it into your mail client to send: Threadline only has read-only access to mail."}
    return {"executed": False, "message": f"{p.tool} is not supported for automatic execution."}
