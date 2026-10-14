from datetime import UTC, datetime, timedelta

from app.db import models as m
from app.intelligence.proactive import Draft, feedback_factor, rank
from app.intelligence.project_association import associate, score_projects


def test_rank_orders_by_importance_urgency_confidence_recency() -> None:
    now = datetime(2026, 10, 14, tzinfo=UTC)
    hi = Draft("x", "t", "e", [], 0.9, 0.9, 0.9, now)
    lo = Draft("x", "t", "e", [], 0.5, 0.3, 0.2, now - timedelta(days=40))
    assert rank(hi, now, 1.0) > rank(lo, now, 1.0)
    assert rank(hi, now, 0.5) < rank(hi, now, 1.0)


def test_feedback_shrinks_unhelpful_kinds(db, user) -> None:
    for i in range(4):
        db.add(m.Insight(user_id=user.id, kind="awaiting_my_reply", title="t", explanation="e", confidence=1, importance=1, urgency=1,
                         score=1, dedupe_key=f"k{i}", feedback="not_useful"))
    db.flush()
    assert feedback_factor(db, user.id, "awaiting_my_reply") < 0.5
    assert feedback_factor(db, user.id, "other") == 1.0


def test_project_association_reasons_threshold_and_corrections(db, user) -> None:
    p = m.Project(user_id=user.id, name="Atlas", keywords=["migration"])
    q = m.Project(user_id=user.id, name="Phoenix")
    db.add_all([p, q])
    db.flush()
    s = score_projects(db, user.id, title="Atlas timeline", body="the migration plan", participant_ids=set())
    assert s[0].project_name == "Atlas" and any("title mentions" in r for r in s[0].reasons)
    pid, inf = associate(db, user.id, subject_type="email", subject_id="e1", title="Atlas timeline", body="", participant_ids=set())
    assert pid == p.id and inf.status == "auto"
    pid2, inf2 = associate(db, user.id, subject_type="email", subject_id="e2", title="hello", body="about the migration", participant_ids=set())
    assert pid2 is None and inf2 is None  # below the suggestion threshold
    # a user correction for a thread becomes a rule
    db.add(m.Correction(user_id=user.id, kind="project_association", target_type="email", target_id="e1", before={},
                        after={"project_id": q.id}, rule_key="thread:t1"))
    db.flush()
    pid3, _ = associate(db, user.id, subject_type="email", subject_id="e3", title="Atlas again", body="", participant_ids=set(), rule_keys=["thread:t1"])
    assert pid3 == q.id
