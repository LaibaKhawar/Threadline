from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import current_session, current_user, get_db, rate_limit
from app.core.config import get_settings
from app.core.security import CSRF_COOKIE, SESSION_COOKIE, csrf_for_session, hash_token, new_session_token, verify_password
from app.db import models as m
from app.services.accounts import create_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    display_name: str = Field(min_length=1, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


def _same_origin(request: Request) -> None:
    """Block cross-site form posts to the auth endpoints (login CSRF). Browsers always send Origin on POST."""
    origin = request.headers.get("origin")
    if not origin:
        return
    allowed = set(get_settings().cors_origins)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    if origin in allowed or origin.split("://", 1)[-1] == host:
        return
    raise HTTPException(403, "cross-site request rejected")


def _start_session(db: Session, user: m.User, request: Request, response: Response) -> dict[str, object]:
    s = get_settings()
    token = new_session_token()
    db.add(m.Session(user_id=user.id, token_hash=hash_token(token), expires_at=datetime.now(UTC) + timedelta(hours=s.session_ttl_hours),
                     user_agent=(request.headers.get("user-agent") or "")[:300]))
    db.add(m.AuditLog(user_id=user.id, actor="user", action="login", details={"ip": request.client.host if request.client else None}))
    db.commit()
    max_age = s.session_ttl_hours * 3600
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=s.cookie_secure, samesite="lax", max_age=max_age, path="/")
    # Double-submit CSRF token bound to the session (readable by the SPA, useless without the HttpOnly session cookie).
    response.set_cookie(CSRF_COOKIE, csrf_for_session(token), httponly=False, secure=s.cookie_secure, samesite="lax", max_age=max_age, path="/")
    return {"user": user_out(db, user)}


def user_out(db: Session, user: m.User) -> dict[str, object]:
    st = db.get(m.UserSettings, user.id)
    return {"id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role, "is_demo": user.is_demo,
            "onboarding_completed": bool(st and st.onboarding_completed), "ai_mode": st.ai_mode if st else "LOCAL"}


@router.post("/register", dependencies=[Depends(rate_limit("auth", auth=True))])
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict[str, object]:
    _same_origin(request)
    if not get_settings().allow_registration:
        raise HTTPException(403, "registration is disabled")
    if db.scalar(select(m.User).where(m.User.email == body.email.lower())):
        raise HTTPException(409, "an account with this email already exists")
    first = db.scalar(select(m.User.id).where(m.User.is_demo.is_(False)).limit(1)) is None
    user = create_user(db, email=body.email, password=body.password, display_name=body.display_name, role="admin" if first else "user")
    db.commit()
    return _start_session(db, user, request, response)


@router.post("/login", dependencies=[Depends(rate_limit("auth", auth=True))])
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict[str, object]:
    _same_origin(request)
    from app.api.deps import limiter

    if not limiter.check(body.email.lower(), "login-account", get_settings().auth_rate_limit_per_minute):
        raise HTTPException(429, "too many attempts for this account; try again in a minute")
    user = db.scalar(select(m.User).where(m.User.email == body.email.lower()))
    if user is None or not verify_password(user.password_hash, body.password):
        raise HTTPException(401, "invalid email or password")
    return _start_session(db, user, request, response)


@router.post("/logout")
def logout(response: Response, sess: m.Session = Depends(current_session), db: Session = Depends(get_db)) -> dict[str, bool]:
    db.execute(delete(m.Session).where(m.Session.id == sess.id))
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"ok": True}


@router.get("/config")
def public_config() -> dict[str, bool]:
    """What the sign-in page may offer (no secrets)."""
    s = get_settings()
    return {"demo_login_enabled": s.demo_login_enabled, "allow_registration": s.allow_registration}


@router.get("/me")
def me(user: m.User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    return {"user": user_out(db, user)}


@router.post("/demo", dependencies=[Depends(rate_limit("demo", auth=True))])
def demo_login(request: Request, response: Response, db: Session = Depends(get_db)) -> dict[str, object]:
    _same_origin(request)
    """Sign in to the synthetic demo workspace (only when DEMO_LOGIN_ENABLED)."""
    if not get_settings().demo_login_enabled:
        raise HTTPException(404, "demo login is disabled")
    from app.demo.world import SELF

    user = db.scalar(select(m.User).where(m.User.email == SELF["email"]))
    if user is None:
        raise HTTPException(503, "demo workspace is not loaded yet; run `make demo`")
    return _start_session(db, user, request, response)
