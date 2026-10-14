"""Integrations, privacy center, settings, onboarding, activity/audit, costs, jobs, evaluation, health."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from app.ai.llm.gateway import cloud_provider, local_provider
from app.api.deps import current_user, workspace
from app.api.serialize import integration_dict, iso
from app.connectors.registry import catalog, get_connector
from app.core.config import get_settings
from app.core.crypto import encrypt_json
from app.db import models as m
from app.db.base import rowcount
from app.ingestion.workspace import Workspace
from app.privacy.policy import CLOUD_ELIGIBLE_OPERATIONS
from app.services.jobs import enqueue

router = APIRouter(prefix="/api", tags=["system"])

# ------------------------------------------------------------------------------------- integrations


@router.get("/integrations/catalog")
def integrations_catalog() -> dict[str, Any]:
    s = get_settings()
    items = catalog()
    for c in items:
        if c["kind"] in ("gmail", "gcal"):
            c["configured"] = bool(s.google_client_id and s.google_client_secret)
        elif c["kind"] == "local_files":
            c["configured"] = bool(s.local_import_roots)
        else:
            c["configured"] = c["implemented"]
    return {"items": items}


@router.get("/integrations")
def integrations(ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    rows = list(ws.db.scalars(select(m.Integration).where(m.Integration.user_id == ws.user_id).order_by(m.Integration.created_at)))
    out = []
    for i in rows:
        st = ws.db.scalar(select(m.SyncState).where(m.SyncState.integration_id == i.id))
        d = integration_dict(i, st)
        d["item_count"] = ws.db.scalar(select(func.count()).select_from(m.SourceItem).where(m.SourceItem.integration_id == i.id,
                                                                                           m.SourceItem.deleted_at.is_(None)))
        out.append(d)
    return {"items": out}


class IntegrationIn(BaseModel):
    kind: str = Field(pattern="^(local_files|demo)$")
    name: str | None = Field(default=None, max_length=200)
    config: dict[str, Any] = Field(default_factory=dict)


@router.post("/integrations")
def create_integration(body: IntegrationIn, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    s = get_settings()
    cls = get_connector(body.kind)
    config = {k: v for k, v in body.config.items() if k in ("path", "markdown_as")}
    _no_demo_writes(ws)
    if body.kind == "local_files":
        if not s.local_import_roots:
            raise HTTPException(403, "local folder import is disabled (set LOCAL_IMPORT_ROOTS to the folders it may read)")
        try:
            cls({**config, "_allowed_roots": s.local_import_roots, "_forbidden_roots": [s.data_dir]}).authenticate()
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc
    integ = m.Integration(user_id=ws.user_id, kind=body.kind, name=body.name or cls.display_name, config=config)
    ws.db.add(integ)
    ws.db.add(m.AuditLog(user_id=ws.user_id, actor="user", action="integration_connected", target_type="integration", target_id=integ.id,
                         details={"kind": body.kind}))
    ws.db.commit()
    return integration_dict(integ)


def _no_demo_writes(ws: Workspace) -> None:
    """The demo account is shared by every visitor, so it may not pull in files or connect accounts."""
    user = ws.db.get(m.User, ws.user_id)
    if user is not None and user.is_demo:
        raise HTTPException(403, "disabled in the shared demo workspace; create your own account to connect sources")


@router.post("/integrations/{iid}/sync")
def sync(iid: str, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    integ = ws.db.get(m.Integration, iid)
    if not integ or integ.user_id != ws.user_id:
        raise HTTPException(404, "not found")
    if integ.kind in ("notes", "uploads"):
        raise HTTPException(400, "internal sources do not sync")
    job = enqueue(ws.db, kind="sync", user_id=ws.user_id, payload={"integration_id": iid}, idempotency_key=f"sync:{iid}")
    return {"job_id": job.id, "status": job.status}


class PrivacyFlags(BaseModel):
    store_locally: bool | None = None
    local_ai_allowed: bool | None = None
    cloud_ai_allowed: bool | None = None


@router.patch("/integrations/{iid}")
def patch_integration(iid: str, body: PrivacyFlags, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    integ = ws.db.get(m.Integration, iid)
    if not integ or integ.user_id != ws.user_id:
        raise HTTPException(404, "not found")
    before = {"store_locally": integ.store_locally, "local_ai_allowed": integ.local_ai_allowed, "cloud_ai_allowed": integ.cloud_ai_allowed}
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(integ, k, v)
    if not integ.local_ai_allowed:
        integ.cloud_ai_allowed = False  # cloud implies local permission
    ws.db.add(m.AuditLog(user_id=ws.user_id, actor="user", action="privacy_source_changed", target_type="integration", target_id=iid,
                         details={"before": before, "after": body.model_dump(exclude_unset=True)}))
    ws.db.commit()
    return integration_dict(integ)


@router.post("/integrations/{iid}/disconnect")
def disconnect(iid: str, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    integ = ws.db.get(m.Integration, iid)
    if not integ or integ.user_id != ws.user_id:
        raise HTTPException(404, "not found")
    cred = ws.db.scalar(select(m.Credential).where(m.Credential.integration_id == iid))
    if cred:
        try:
            from app.core.crypto import decrypt_json

            get_connector(integ.kind)(integ.config, decrypt_json(cred.ciphertext)).revoke()
        except Exception:  # noqa: S110  revocation is best effort; the local token is deleted regardless
            pass
        ws.db.delete(cred)
    integ.status = "revoked"
    ws.db.add(m.AuditLog(user_id=ws.user_id, actor="user", action="integration_disconnected", target_type="integration", target_id=iid))
    ws.db.commit()
    return integration_dict(integ)


@router.delete("/integrations/{iid}/data")
def delete_source_data(iid: str, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    """Delete every item imported from this source and everything derived from it."""
    integ = ws.db.get(m.Integration, iid)
    if not integ or integ.user_id != ws.user_id:
        raise HTTPException(404, "not found")
    from app.documents.service import delete_file
    from app.ingestion.purge import purge_source_item

    n = 0
    for si in list(ws.db.scalars(select(m.SourceItem).where(m.SourceItem.integration_id == iid))):
        for d in ws.db.scalars(select(m.Document).where(m.Document.source_item_id == si.id)):
            delete_file(d)
        purge_source_item(ws.db, si)
        ws.db.delete(si)
        n += 1
    st = ws.db.scalar(select(m.SyncState).where(m.SyncState.integration_id == iid))
    if st:
        ws.db.delete(st)
    ws.db.add(m.AuditLog(user_id=ws.user_id, actor="user", action="source_data_deleted", target_type="integration", target_id=iid, details={"items": n}))
    ws.db.commit()
    return {"deleted_items": n}


@router.post("/integrations/google/{kind}/start")
def google_start(kind: str, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    _no_demo_writes(ws)
    from app.connectors.google import build_auth_url

    s = get_settings()
    if kind not in ("gmail", "gcal"):
        raise HTTPException(400, "unknown kind")
    if not (s.google_client_id and s.google_client_secret):
        raise HTTPException(400, "Google OAuth is not configured (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)")
    a = build_auth_url(s.google_client_id, s.google_redirect_uri, kind)
    integ = m.Integration(user_id=ws.user_id, kind=kind, name="Gmail" if kind == "gmail" else "Google Calendar", status="pending",
                          config={})
    ws.db.add(integ)
    ws.db.flush()
    # state + PKCE verifier stored server-side (encrypted) to validate the callback
    ws.db.add(m.Credential(integration_id=integ.id, ciphertext=encrypt_json({"oauth_state": a["state"], "verifier": a["verifier"]})))
    ws.db.commit()
    return {"url": a["url"], "integration_id": integ.id}


class OAuthCallback(BaseModel):
    integration_id: str
    code: str
    state: str


@router.post("/integrations/google/callback")
def google_callback(body: OAuthCallback, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    import hmac

    from app.connectors.google import exchange_code
    from app.core.crypto import decrypt_json

    s = get_settings()
    integ = ws.db.get(m.Integration, body.integration_id)
    if not integ or integ.user_id != ws.user_id:
        raise HTTPException(404, "not found")
    cred = ws.db.scalar(select(m.Credential).where(m.Credential.integration_id == integ.id))
    pending = decrypt_json(cred.ciphertext) if cred else {}
    if not pending.get("oauth_state") or not hmac.compare_digest(pending["oauth_state"], body.state):
        raise HTTPException(400, "OAuth state mismatch")
    tok = exchange_code(s.google_client_id, s.google_client_secret, s.google_redirect_uri, body.code, pending["verifier"])
    assert cred is not None
    cred.ciphertext = encrypt_json({k: tok[k] for k in ("access_token", "refresh_token", "expires_at", "scope") if k in tok})
    integ.status = "connected"
    ws.db.commit()
    return integration_dict(integ)


@router.get("/jobs/{jid}")
def job(jid: str, user: m.User = Depends(current_user), ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    j = ws.db.get(m.Job, jid)
    if not j or j.user_id != user.id:
        raise HTTPException(404, "not found")
    return {"id": j.id, "kind": j.kind, "status": j.status, "attempts": j.attempts, "progress": j.progress, "error": j.error,
            "created_at": iso(j.created_at), "finished_at": iso(j.finished_at)}


@router.get("/jobs")
def jobs(ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    rows = list(ws.db.scalars(select(m.Job).where(m.Job.user_id == ws.user_id).order_by(m.Job.created_at.desc()).limit(50)))
    pending_events = ws.db.scalar(select(func.count()).select_from(m.DomainEvent).where(m.DomainEvent.user_id == ws.user_id,
                                                                                         m.DomainEvent.status.in_(["pending", "queued", "processing"])))
    failed_events = ws.db.scalar(select(func.count()).select_from(m.DomainEvent).where(m.DomainEvent.user_id == ws.user_id,
                                                                                        m.DomainEvent.status.in_(["failed", "dead"])))
    return {"items": [{"id": j.id, "kind": j.kind, "status": j.status, "attempts": j.attempts, "progress": j.progress, "error": j.error,
                       "created_at": iso(j.created_at), "finished_at": iso(j.finished_at)} for j in rows],
            "events": {"pending": pending_events, "failed": failed_events}}


# ------------------------------------------------------------------------------------- privacy center


class PrivacyIn(BaseModel):
    ai_mode: str | None = Field(default=None, pattern="^(LOCAL|HYBRID|CLOUD)$")
    cloud_allowed_operations: list[str] | None = None
    telemetry_opt_in: bool | None = None


@router.get("/privacy")
def privacy(ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    s = get_settings()
    db = ws.db
    srcs = []
    for i in db.scalars(select(m.Integration).where(m.Integration.user_id == ws.user_id)):
        st = db.scalar(select(m.SyncState).where(m.SyncState.integration_id == i.id))
        srcs.append({**integration_dict(i, st), "items": db.scalar(select(func.count()).select_from(m.SourceItem).where(
            m.SourceItem.integration_id == i.id, m.SourceItem.deleted_at.is_(None)))})
    from datetime import UTC, datetime

    since = datetime.now(UTC) - timedelta(days=30)  # real time: LLM call rows are stamped with wall-clock time
    calls = dict(db.execute(select(m.LLMCall.locality, func.count()).where(m.LLMCall.user_id == ws.user_id, m.LLMCall.created_at >= since)
                            .group_by(m.LLMCall.locality)).all())
    return {"ai_mode": ws.settings.ai_mode, "cloud_configured": s.cloud_configured, "cloud_model": s.cloud_model or None,
            "cloud_allowed_operations": ws.settings.cloud_allowed_operations or [], "cloud_eligible_operations": list(CLOUD_ELIGIBLE_OPERATIONS),
            "telemetry_opt_in": ws.settings.telemetry_opt_in, "telemetry_transmits": False, "sources": srcs,
            "llm_calls_by_locality": calls, "llm_calls_window_days": 30, "embeddings": "always computed locally", "stored_at": "this machine (PostgreSQL + local file store)"}


@router.put("/privacy")
def set_privacy(body: PrivacyIn, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    before = {"ai_mode": ws.settings.ai_mode, "ops": ws.settings.cloud_allowed_operations}
    if body.ai_mode:
        ws.settings.ai_mode = body.ai_mode
    if body.cloud_allowed_operations is not None:
        ws.settings.cloud_allowed_operations = [o for o in body.cloud_allowed_operations if o in CLOUD_ELIGIBLE_OPERATIONS]
    if body.telemetry_opt_in is not None:
        ws.settings.telemetry_opt_in = body.telemetry_opt_in
    ws.db.add(m.AuditLog(user_id=ws.user_id, actor="user", action="privacy_mode_changed", details={"before": before, "after": body.model_dump(exclude_unset=True)}))
    ws.db.commit()
    return privacy(ws)


@router.get("/privacy/inventory")
def inventory(ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    """What is stored about you, by type."""
    db = ws.db
    out = {}
    for name, model in (("emails", m.Email), ("meetings", m.CalendarEvent), ("documents", m.Document), ("notes", m.Note), ("chunks", m.Chunk),
                        ("people", m.Person), ("organizations", m.Organization), ("commitments", m.Commitment), ("decisions", m.Decision),
                        ("tasks", m.Task), ("relationships", m.Relationship), ("memories", m.Memory), ("evidence", m.Evidence),
                        ("insights", m.Insight), ("agent_runs", m.AgentRun), ("llm_calls", m.LLMCall), ("audit_log", m.AuditLog)):
        out[name] = db.scalar(select(func.count()).select_from(model).where(model.user_id == ws.user_id))
    return {"counts": out}


@router.get("/privacy/export")
def export(ws: Workspace = Depends(workspace)) -> StreamingResponse:
    """Download everything stored for this account as JSON files in a zip (credentials excluded)."""
    db = ws.db
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, model in (("emails", m.Email), ("events", m.CalendarEvent), ("documents", m.Document), ("notes", m.Note),
                            ("people", m.Person), ("person_aliases", m.PersonAlias), ("organizations", m.Organization), ("projects", m.Project),
                            ("tasks", m.Task), ("commitments", m.Commitment), ("decisions", m.Decision), ("relationships", m.Relationship),
                            ("memories", m.Memory), ("evidence", m.Evidence), ("timeline", m.TimelineEvent), ("insights", m.Insight),
                            ("agent_runs", m.AgentRun), ("corrections", m.Correction), ("llm_calls", m.LLMCall), ("audit_log", m.AuditLog)):
            rows = []
            for r in db.scalars(select(model).where(model.user_id == ws.user_id)):
                d = {c.name: getattr(r, c.key, None) for c in model.__table__.columns if c.name not in ("embedding", "tsv", "password_hash")}
                rows.append(d)
            z.writestr(f"{name}.json", json.dumps(rows, default=str, indent=1))
        z.writestr("README.txt", "Threadline data export. Connector credentials are excluded. Original uploaded files are not included; "
                                 "download them from the Documents page.")
    buf.seek(0)
    ws.db.add(m.AuditLog(user_id=ws.user_id, actor="user", action="data_exported"))
    ws.db.commit()
    return StreamingResponse(buf, media_type="application/zip", headers={"Content-Disposition": "attachment; filename=threadline-export.zip"})


class ClearIn(BaseModel):
    scope: str = Field(pattern="^(ai_memories|conversations|everything)$")
    confirm: str


@router.post("/privacy/clear")
def clear(body: ClearIn, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    if body.confirm != "DELETE":
        raise HTTPException(400, "type DELETE to confirm")
    db, uid = ws.db, ws.user_id
    deleted: dict[str, int] = {}
    # heterogeneous model lists: each entry is a UserOwned model, so ``model.user_id`` is always present
    ai_models: list[Any] = [m.Memory, m.Insight, m.Notification, m.Inference, m.FulfillmentCandidate, m.Evidence, m.TimelineEvent, m.MergeCandidate]
    if body.scope in ("ai_memories", "everything"):
        for model in ai_models:
            deleted[model.__tablename__] = rowcount(db.execute(delete(model).where(model.user_id == uid))) or 0
        deleted["relationships"] = rowcount(db.execute(delete(m.Relationship).where(m.Relationship.user_id == uid, m.Relationship.origin != "user"))) or 0
        deleted["ai_commitments"] = rowcount(db.execute(delete(m.Commitment).where(m.Commitment.user_id == uid, m.Commitment.user_modified.is_(False)))) or 0
        deleted["ai_decisions"] = rowcount(db.execute(delete(m.Decision).where(m.Decision.user_id == uid, m.Decision.user_confirmed.is_(False)))) or 0
        deleted["ai_tasks"] = rowcount(db.execute(delete(m.Task).where(m.Task.user_id == uid, m.Task.ai_suggested.is_(True), m.Task.user_modified.is_(False)))) or 0
    if body.scope in ("conversations", "everything"):
        deleted["conversations"] = rowcount(db.execute(delete(m.Conversation).where(m.Conversation.user_id == uid))) or 0
        deleted["agent_runs"] = rowcount(db.execute(delete(m.AgentRun).where(m.AgentRun.user_id == uid))) or 0
    if body.scope == "everything":
        from app.documents.service import delete_file

        for d in db.scalars(select(m.Document).where(m.Document.user_id == uid)):
            delete_file(d)
        owned_models: tuple[Any, ...] = (m.Chunk, m.Email, m.EmailThread, m.CalendarEvent, m.Document, m.Note, m.Task, m.Commitment,
                                         m.Decision, m.SourceItem, m.Relationship, m.PersonAlias, m.Correction, m.ActionProposal,
                                         m.Topic, m.Project)
        for model in owned_models:
            deleted[model.__tablename__] = rowcount(db.execute(delete(model).where(model.user_id == uid))) or 0
        # names and addresses harvested from mail go too (your own profile stays so the account keeps working)
        deleted["people"] = rowcount(db.execute(delete(m.Person).where(m.Person.user_id == uid, m.Person.is_self.is_(False)))) or 0
        deleted["organizations"] = rowcount(db.execute(delete(m.Organization).where(m.Organization.user_id == uid))) or 0
        for st in db.scalars(select(m.SyncState).join(m.Integration, m.Integration.id == m.SyncState.integration_id).where(m.Integration.user_id == uid)):
            db.delete(st)
    db.add(m.AuditLog(user_id=uid, actor="user", action=f"data_cleared:{body.scope}", details=deleted))
    db.commit()
    return {"deleted": deleted, "note": "AI memories can be rebuilt by reprocessing your sources (Settings → Rebuild memory)."}


# ------------------------------------------------------------------------------------- settings / onboarding


class SettingsIn(BaseModel):
    reasoning_model: str | None = None
    extraction_model: str | None = None
    llm_extraction_enabled: bool | None = None
    timezone: str | None = None
    procedural_prefs: list[str] | None = None


@router.get("/settings")
def settings(ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    s = get_settings()
    st = ws.settings
    return {"reasoning_model": st.reasoning_model or s.reasoning_model, "extraction_model": st.extraction_model or s.extraction_model,
            "embedding": {"provider": s.embedding_provider, "model": s.embedding_model, "dim": s.embedding_dim},
            "llm_extraction_enabled": st.llm_extraction_enabled, "timezone": st.timezone, "auto_create_tasks": st.auto_create_tasks,
            "procedural_prefs": ws.memory.procedural(), "clock_override": iso(st.clock_override), "ollama_url": s.ollama_base_url}


@router.put("/settings")
def set_settings(body: SettingsIn, ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    st = ws.settings
    data = body.model_dump(exclude_unset=True)
    for k in ("reasoning_model", "extraction_model", "llm_extraction_enabled", "timezone"):
        if k in data:
            setattr(st, k, data[k])
    if body.procedural_prefs is not None:
        for r in ws.db.scalars(select(m.Memory).where(m.Memory.user_id == ws.user_id, m.Memory.kind == "procedural")):
            r.status = "archived"
        for p in body.procedural_prefs:
            if p.strip():
                ws.memory.add_procedural(p[:500])
    ws.db.commit()
    return settings(ws)


@router.get("/models/health")
def models_health(ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    local = local_provider().health_check()
    cloud = cloud_provider()
    from app.ai.embeddings.base import get_embedder

    e = get_embedder()
    return {"local": local, "cloud": {"configured": cloud is not None, "provider": cloud.name if cloud else None},
            "embedder": {"provider": e.name, "model": e.model, "dim": e.dim}}


@router.post("/onboarding/demo")
def onboarding_demo(user: m.User = Depends(current_user), ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    """Import the synthetic demo workspace into the current account (progress via the returned job)."""
    job = enqueue(ws.db, kind="load_demo", user_id=user.id, payload={}, idempotency_key=f"demo:{user.id}")
    return {"job_id": job.id}


class OnboardingIn(BaseModel):
    completed: bool = True


@router.post("/onboarding/complete")
def onboarding_complete(body: OnboardingIn, ws: Workspace = Depends(workspace)) -> dict[str, bool]:
    ws.settings.onboarding_completed = body.completed
    ws.db.commit()
    return {"ok": True}


@router.post("/memory/rebuild")
def rebuild(ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    job = enqueue(ws.db, kind="reprocess", user_id=ws.user_id, payload={}, idempotency_key=f"reprocess:{ws.user_id}")
    return {"job_id": job.id}


@router.post("/intelligence/run")
def run_intelligence(ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    job = enqueue(ws.db, kind="proactive", user_id=ws.user_id, payload={}, idempotency_key=f"proactive:{ws.user_id}")
    return {"job_id": job.id}


# ------------------------------------------------------------------------------------- activity / audit / costs


@router.get("/activity")
def activity(kind: str = Query("audit", pattern="^(audit|runs|llm|tools)$"), limit: int = Query(100, le=500),
             ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    db = ws.db
    if kind == "audit":
        rows = db.scalars(select(m.AuditLog).where(m.AuditLog.user_id == ws.user_id).order_by(m.AuditLog.created_at.desc()).limit(limit))
        return {"items": [{"id": r.id, "actor": r.actor, "action": r.action, "target": {"type": r.target_type, "id": r.target_id},
                           "details": r.details, "created_at": iso(r.created_at)} for r in rows]}
    if kind == "runs":
        rows2 = db.scalars(select(m.AgentRun).where(m.AgentRun.user_id == ws.user_id).order_by(m.AgentRun.created_at.desc()).limit(limit))
        return {"items": [{"id": r.id, "question": r.question, "status": r.status, "mode": r.answer_mode, "latency_ms": r.latency_ms,
                           "model": r.model, "citations": len(r.citations or []), "verification": r.verification,
                           "tokens": r.input_tokens + r.output_tokens, "cost_usd": r.cost_usd, "created_at": iso(r.created_at)} for r in rows2]}
    if kind == "tools":
        rows3 = db.scalars(select(m.ToolExecution).where(m.ToolExecution.user_id == ws.user_id).order_by(m.ToolExecution.created_at.desc()).limit(limit))
        return {"items": [{"id": t.id, "run_id": t.run_id, "tool": t.tool, "access": t.access, "status": t.status, "latency_ms": t.latency_ms,
                           "result_count": t.result_count, "created_at": iso(t.created_at)} for t in rows3]}
    rows4 = db.scalars(select(m.LLMCall).where(m.LLMCall.user_id == ws.user_id).order_by(m.LLMCall.created_at.desc()).limit(limit))
    return {"items": [{"id": c.id, "provider": c.provider, "model": c.model, "locality": c.locality, "operation": c.operation,
                       "status": c.status, "input_tokens": c.input_tokens, "output_tokens": c.output_tokens, "cost_usd": c.cost_usd,
                       "latency_ms": c.latency_ms, "source_types": c.source_types, "created_at": iso(c.created_at)} for c in rows4]}


@router.get("/costs")
def costs(ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    out = {}
    for label, delta in (("today", timedelta(days=1)), ("week", timedelta(days=7)), ("month", timedelta(days=30))):
        rows = ws.db.execute(select(m.LLMCall.locality, func.count(), func.sum(m.LLMCall.input_tokens), func.sum(m.LLMCall.output_tokens),
                                    func.sum(m.LLMCall.cost_usd), func.avg(m.LLMCall.latency_ms))
                             .where(m.LLMCall.user_id == ws.user_id, m.LLMCall.created_at >= now - delta).group_by(m.LLMCall.locality)).all()
        out[label] = {loc: {"calls": n, "input_tokens": int(i or 0), "output_tokens": int(o or 0), "cost_usd": round(float(c or 0), 6),
                            "avg_latency_ms": int(lat or 0)} for loc, n, i, o, c, lat in rows}
    per_run = [{"run_id": r.id, "question": r.question[:80], "tokens": r.input_tokens + r.output_tokens, "cost_usd": r.cost_usd,
                "latency_ms": r.latency_ms} for r in ws.db.scalars(select(m.AgentRun).where(m.AgentRun.user_id == ws.user_id)
                                                                   .order_by(m.AgentRun.created_at.desc()).limit(20))]
    return {"periods": out, "per_run": per_run,
            "note": "Local inference is reported as compute (tokens and latency) with $0 cost; cloud cost uses the configured per-token rates."}


# ------------------------------------------------------------------------------------- evaluation


@router.get("/evaluation")
def evaluation(user: m.User = Depends(current_user), ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    rows = list(ws.db.scalars(select(m.EvaluationRun).order_by(m.EvaluationRun.created_at.desc()).limit(200)))
    latest: dict[str, Any] = {}
    for r in rows:
        key = f"{r.suite}:{(r.config or {}).get('variant', 'default')}"
        if key not in latest:
            latest[key] = {"id": r.id, "suite": r.suite, "config": r.config, "metrics": r.metrics, "created_at": iso(r.created_at)}
    return {"latest": list(latest.values()), "history": [{"id": r.id, "suite": r.suite, "variant": (r.config or {}).get("variant"),
                                                         "metrics": r.metrics, "created_at": iso(r.created_at)} for r in rows]}


@router.get("/evaluation/{rid}")
def evaluation_run(rid: str, user: m.User = Depends(current_user), ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    r = ws.db.get(m.EvaluationRun, rid)
    if not r:
        raise HTTPException(404, "not found")
    return {"id": r.id, "suite": r.suite, "config": r.config, "metrics": r.metrics, "details": r.details, "created_at": iso(r.created_at)}


class EvalIn(BaseModel):
    suites: list[str] | None = None
    use_llm: bool = False


@router.post("/evaluation/run")
def run_eval(body: EvalIn, user: m.User = Depends(current_user), ws: Workspace = Depends(workspace)) -> dict[str, Any]:
    if user.role != "admin":
        raise HTTPException(403, "evaluation runs are system-wide; only an admin can start them")
    job = enqueue(ws.db, kind="evaluation", user_id=user.id, payload={"suites": body.suites, "use_llm": body.use_llm},
                  idempotency_key="evaluation", max_attempts=1)
    return {"job_id": job.id}
