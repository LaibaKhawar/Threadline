from datetime import UTC, date, datetime

from app.extraction.decisions import extract_blockers, extract_deadline_changes, extract_decisions, extract_employment

REF = datetime(2026, 9, 15, tzinfo=UTC)


def test_decisions_with_topic_and_rejected_options() -> None:
    d = extract_decisions("We've decided to use PostgreSQL rather than MongoDB.")[0]
    assert (d.topic, d.chosen, d.rejected) == ("database", "PostgreSQL", ["MongoDB"])
    d2 = extract_decisions("We are switching from MongoDB to Postgres.")[0]
    assert (d2.chosen, d2.rejected) == ("Postgres", ["MongoDB"])
    d3 = extract_decisions("We agreed to run the Orion pilot on AWS rather than GCP.")[0]
    assert (d3.topic, d3.chosen, d3.rejected) == ("cloud provider", "AWS", ["GCP"])
    assert extract_decisions("Change of plan: we've decided to go back to MongoDB.")[0].reverses_previous


def test_questions_and_proposals_are_not_decisions() -> None:
    assert extract_decisions("Should we use Kafka?") == []
    assert extract_decisions("I propose we use Kafka.") == []
    assert extract_decisions("Maybe we decided to use Kafka.") == []


def test_deadline_moves_and_settings() -> None:
    moved = extract_deadline_changes("The Atlas launch has been moved to October 23.", REF)[0]
    assert (moved.kind, moved.subject, moved.new_due_at.date()) == ("moved", "Atlas launch", date(2026, 10, 23))
    setd = extract_deadline_changes("The Atlas launch is scheduled for October 9.", REF)[0]
    assert setd.kind == "set" and setd.new_due_at.date() == date(2026, 10, 9)
    assert extract_deadline_changes("The deadline for the mockups has been moved to Oct 2.", REF)[0].subject == "deadline for mockups"
    assert extract_deadline_changes("New deadline: Oct 20", REF)[0].new_due_at.date() == date(2026, 10, 20)


def test_employment_facts() -> None:
    f = extract_employment("Quick news: I've joined Acme Corp as VP Engineering.", "", "Sarah Chen")[0]
    assert (f.person, f.organization, f.title, f.kind) == ("Sarah Chen", "Acme Corp", "VP Engineering", "joined")
    sig = extract_employment("Thanks", "Sarah Chen\nDirector of Data, Northwind Analytics", "Sarah Chen")[0]
    assert sig.organization == "Northwind Analytics" and sig.kind == "signature"


def test_blockers() -> None:
    bs = extract_blockers("The vendor contract is blocked on legal. We're still waiting on Ahmed for the budget approval.")
    assert [(b.blocked_item, b.blocked_by) for b in bs] == [("vendor contract", "legal"), ("budget approval", "Ahmed")]
