from datetime import UTC, date, datetime

import pytest

from app.extraction.commitments import ADDRESSEE, SPEAKER, ExtractionContext, extract_commitments, extract_completions

CTX = ExtractionContext(sent_at=datetime(2026, 9, 15, 10, tzinfo=UTC), subject="Architecture review")


def one(text: str):  # type: ignore[no-untyped-def]
    cs = extract_commitments(text, CTX)
    assert len(cs) == 1, cs
    return cs[0]


def test_spec_example_commitment_dependency_and_request() -> None:
    text = "Hi Laiba, I'll send the updated architecture document by Friday. Once you've reviewed it, please share your feedback with Ahmed."
    cs = extract_commitments(text, CTX)
    assert len(cs) == 2
    send, share = cs
    assert (send.kind, send.actor, send.action, send.object) == ("commitment", SPEAKER, "send", "updated architecture document")
    assert send.due_at and send.due_at.date() == date(2026, 9, 18)
    assert (share.kind, share.actor, share.action, share.recipient) == ("request", ADDRESSEE, "share", "Ahmed")
    assert share.depends_on_index == 0
    assert text[send.span_start : send.span_end] == send.source_span


@pytest.mark.parametrize(
    ("text", "kind", "actor", "action"),
    [
        ("I'll send the report tomorrow.", "commitment", SPEAKER, "send"),
        ("We will finish migration by Friday.", "commitment", SPEAKER, "finish"),
        ("Can you get this back to me next week?", "request", ADDRESSEE, "deliver"),
        ("Sarah said she'll review the contract.", "commitment", "Sarah", "review"),
        ("Ahmed will share the migration runbook by Thursday.", "commitment", "Ahmed", "share"),
        ("Could you please approve the Q4 budget by end of week?", "request", ADDRESSEE, "approve"),
        ("I'll have the numbers to you by Monday.", "commitment", SPEAKER, "deliver"),
        ("Maybe we can finish this next month.", "intention", SPEAKER, "finish"),
        ("I'll get back to you on pricing by Wednesday.", "commitment", SPEAKER, "reply"),
        ("Ahmed, can you send me the vendor shortlist by Thursday?", "request", "Ahmed", "send"),
    ],
)
def test_commitment_kinds(text: str, kind: str, actor: str, action: str) -> None:
    c = one(text)
    assert (c.kind, c.actor, c.action) == (kind, actor, action)


def test_hedged_intentions_have_low_confidence() -> None:
    c = one("I'll try to look at the budget sometime next week.")
    assert c.kind == "intention" and c.confidence <= 0.5


@pytest.mark.parametrize(
    "text",
    ["I sent it yesterday.", "I won't be able to make the demo.", "Can you believe it?", "We'll be back Tuesday.",
     "Ahmed owns the technical plan.", "Please use this one from now on.", "Thanks for the update, see you Friday."],
)
def test_non_commitments(text: str) -> None:
    assert extract_commitments(text, CTX) == []


def test_completions_and_cancellations() -> None:
    comps = extract_completions("Attached is the final Project Atlas proposal. We no longer need the vendor comparison.", CTX)
    assert [(c.kind, c.object) for c in comps] == [("completed", "final Project Atlas proposal"), ("cancelled", "vendor comparison")]
    assert extract_completions("The security review for Atlas is done.", CTX)[0].kind == "completed"
    # "drop" in ordinary prose is not a cancellation
    assert all(c.kind != "cancelled" for c in extract_completions("most users drop at the data step", CTX))


def test_pronoun_object_resolves_to_previous_noun_phrase() -> None:
    ctx = ExtractionContext(sent_at=CTX.sent_at, subject="Orion", source_kind="meeting")
    c = extract_commitments("John asked for the pilot proposal; Alex agreed to send it.", ctx)[0]
    assert (c.actor, c.object) == ("Alex", "pilot proposal")


def test_meeting_action_items() -> None:
    ctx = ExtractionContext(sent_at=CTX.sent_at, source_kind="meeting")
    cs = extract_commitments("Action items:\n- Priya to draft the validation plan by Aug 14\n- Laiba to schedule the review", ctx)
    assert [(c.actor, c.action) for c in cs] == [("Priya", "draft"), ("Laiba", "schedule")]


def test_have_x_ready_does_not_crash_and_means_deliver() -> None:
    # regression: "can have a first draft ready" used to parse "a" as the verb and crash the extractor
    c = one("I can have a first draft ready in two weeks.")
    assert (c.action, c.object, c.due_at.date()) == ("deliver", "first draft", date(2026, 9, 29))
