"""Create the synthetic demo account (Alex Morgan) and load its workspace.

    python -m scripts.seed_demo              # (re)create the demo account
    python -m scripts.seed_demo --if-missing # only if it does not exist (used by docker compose)
"""

from __future__ import annotations

import argparse
import os
import secrets

from sqlalchemy import select

from app.core.config import get_settings
from app.db import models as m
from app.db.session import SessionLocal
from app.demo.world import SELF
from app.services.accounts import create_user, load_demo_workspace


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--if-missing", action="store_true")
    args = ap.parse_args()
    s = get_settings()
    s.events_eager = True  # process the demo synchronously during seeding
    db = SessionLocal()
    existing = db.scalar(select(m.User).where(m.User.email == SELF["email"]))
    if existing and args.if_missing:
        print("demo account exists; skipping")
        return
    if existing:
        db.delete(existing)
        db.commit()
    # The demo account is reached through the one-click demo login; its password is random and unused.
    pw = os.environ.get("DEMO_PASSWORD") or secrets.token_urlsafe(24)
    user = create_user(db, email=SELF["email"], password=pw, display_name=SELF["name"], is_demo=True)
    db.commit()
    load_demo_workspace(db, user)
    print("demo workspace loaded for", SELF["email"])


if __name__ == "__main__":
    main()
