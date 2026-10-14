"""Shared fixtures. Tests run against a dedicated PostgreSQL database (TEST_DATABASE_URL), migrated with
Alembic at session start (which doubles as the migration test), and use the deterministic hashing
embedder so the suite is fast and offline."""

from __future__ import annotations

import os

os.environ.setdefault("TEST_DATABASE_URL", "postgresql+psycopg://threadline:threadline@localhost:5436/threadline_test")
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ["EMBEDDING_PROVIDER"] = "hashing"
os.environ["EVENTS_EAGER"] = "true"
os.environ["ENVIRONMENT"] = "test"
os.environ["DATA_DIR"] = os.environ.get("TEST_DATA_DIR", "/tmp/threadline-test-data")
os.environ["CLOUD_BASE_URL"] = ""
os.environ["CLOUD_MODEL"] = ""
os.environ["RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["AUTH_RATE_LIMIT_PER_MINUTE"] = "100000"

from collections.abc import Iterator

import pytest
from sqlalchemy import text

from app.ai.embeddings.base import HashingEmbedder, set_embedder
from app.ai.llm.gateway import set_provider_override
from app.core.config import get_settings
from app.db.session import SessionLocal, get_engine

get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def _migrate() -> Iterator[None]:
    from alembic.config import Config

    from alembic import command

    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    set_embedder(HashingEmbedder())
    yield


@pytest.fixture(autouse=True)
def _clean_db() -> Iterator[None]:
    yield
    eng = get_engine()
    with eng.begin() as conn:
        tables = [r[0] for r in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'"))]
        conn.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " RESTART IDENTITY CASCADE"))
    set_provider_override("local", None)
    set_provider_override("cloud", None)
    from app.api.deps import limiter

    limiter.reset()


@pytest.fixture
def db():  # type: ignore[no-untyped-def]
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def user(db):  # type: ignore[no-untyped-def]
    from app.services.accounts import create_user

    u = create_user(db, email="alex@example.com", password="correct-horse-battery", display_name="Alex Morgan")
    db.commit()
    return u


@pytest.fixture
def ws(db, user):  # type: ignore[no-untyped-def]
    from app.ingestion.workspace import Workspace

    return Workspace(db, user.id)
