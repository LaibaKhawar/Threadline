"""FastAPI application."""

from __future__ import annotations

import socket
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.api.routers import assistant, auth, content, core, people, system, work
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging, get_logger, request_id_var
from app.core.metrics import HTTP_LATENCY
from app.db.session import SessionLocal

configure_logging()
log = get_logger("threadline.api")
settings = get_settings()  # validates configuration at startup (fails fast in production)

app = FastAPI(title="Threadline API", version="0.1.0",
              description="Local-first personal memory and intelligence platform. All endpoints are scoped to the signed-in user.")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["content-type", "x-csrf-token", "x-request-id"])


@app.middleware("http")
async def request_context(request: Request, call_next: Any) -> Response:
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    request_id_var.set(rid)
    t0 = time.perf_counter()
    response: Response = await call_next(request)
    route = request.scope.get("route")
    path = getattr(route, "path", "unmatched")
    HTTP_LATENCY.labels(request.method, path, str(response.status_code)).observe(time.perf_counter() - t0)
    response.headers["x-request-id"] = rid
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = response.headers.get("Cache-Control", "no-store")
    if not path.startswith("/api/health"):
        log.info("http_request", method=request.method, path=path, status=response.status_code,
                 duration_ms=round((time.perf_counter() - t0) * 1000, 1))
    return response


@app.exception_handler(AppError)
async def app_error(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse({"error": exc.code, "detail": exc.message, "request_id": request_id_var.get()}, status_code=exc.status_code)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse({"error": "http_error", "detail": exc.detail, "request_id": request_id_var.get()}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    errs = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
    return JSONResponse({"error": "validation_error", "detail": errs, "request_id": request_id_var.get()}, status_code=422)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    # Full details go to the structured log; users get a request id, never a stack trace.
    log.exception("unhandled_error", path=request.url.path, error=type(exc).__name__)
    return JSONResponse({"error": "internal_error", "detail": "Something went wrong. Reference this request id when reporting it.",
                         "request_id": request_id_var.get()}, status_code=500)


for r in (auth.router, core.router, assistant.router, content.router, work.router, people.router, system.router):
    app.include_router(r)


@app.get("/api/health")
def health() -> dict[str, Any]:
    db_ok = True
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok, "version": app.version}


@app.get("/api/system/status")
def system_status() -> dict[str, Any]:
    """Connectivity snapshot for the UI's offline indicator. Checks are local; nothing is sent anywhere."""
    from app.ai.llm.gateway import local_provider

    def internet() -> bool:
        try:
            socket.create_connection(("1.1.1.1", 53), timeout=1.0).close()
            return True
        except OSError:
            return False

    llm = local_provider().health_check()
    online = internet()
    return {"internet": online, "local_llm": llm.get("ok", False), "local_models": llm.get("models", [])[:12],
            "features_offline": ["notes", "tasks", "documents", "local files", "search", "knowledge graph", "local model", "embeddings"],
            "needs_network": ["Gmail sync", "Google Calendar sync", "cloud models"], "mode": "online" if online else "offline"}


@app.get("/metrics", include_in_schema=False)
def metrics(request: Request) -> Response:
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(404)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
