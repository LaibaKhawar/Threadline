"""Held-out commitment statements, written separately from the demo world and not used while
developing the rules. Reference time: Tuesday 2026-09-15 10:00 UTC.

kind: commitment | request | intention | completed | none
actor: SPEAKER | ADDRESSEE | <first name> | None
action: canonical verb expected (None for completed/none)
due: ISO date or None
"""

REFERENCE = "2026-09-15T10:00:00+00:00"

STATEMENTS: list[dict[str, str | None]] = [
    # --- firm commitments by the speaker
    {"text": "I will circulate the revised budget before Thursday.", "kind": "commitment", "actor": "SPEAKER", "action": "share", "due": "2026-09-17"},
    {"text": "I'm going to draft the press release tonight.", "kind": "commitment", "actor": "SPEAKER", "action": "draft", "due": "2026-09-15"},
    {"text": "We'll ship the patch by end of week.", "kind": "commitment", "actor": "SPEAKER", "action": "ship", "due": "2026-09-18"},
    {"text": "I'll review your pull request first thing tomorrow.", "kind": "commitment", "actor": "SPEAKER", "action": "review", "due": "2026-09-16"},
    {"text": "Leave it with me, I'll book the venue for the offsite.", "kind": "commitment", "actor": "SPEAKER", "action": "book", "due": None},
    {"text": "I promise to send over the signed NDA on Monday.", "kind": "commitment", "actor": "SPEAKER", "action": "send", "due": "2026-09-21"},
    {"text": "We are going to migrate the billing tables next week.", "kind": "commitment", "actor": "SPEAKER", "action": "migrate", "due": "2026-09-27"},
    {"text": "I'll get the slides to you by Oct 1.", "kind": "commitment", "actor": "SPEAKER", "action": "deliver", "due": "2026-10-01"},
    {"text": "I can have a first draft ready in two weeks.", "kind": "commitment", "actor": "SPEAKER", "action": "deliver", "due": "2026-09-29"},
    {"text": "Let me set up the staging environment this afternoon.", "kind": "commitment", "actor": "SPEAKER", "action": "set up", "due": "2026-09-15"},
    {"text": "I'll follow up with legal about the indemnity clause.", "kind": "commitment", "actor": "SPEAKER", "action": "follow up", "due": None},
    {"text": "We will publish the postmortem by Sep 30.", "kind": "commitment", "actor": "SPEAKER", "action": "publish", "due": "2026-09-30"},
    # --- third-person commitments
    {"text": "Marcus said he'll update the onboarding checklist.", "kind": "commitment", "actor": "Marcus", "action": "update", "due": None},
    {"text": "Elif will finalize the vendor contract by Friday.", "kind": "commitment", "actor": "Elif", "action": "finalize", "due": "2026-09-18"},
    {"text": "Jordan promised to send the invoice tomorrow.", "kind": "commitment", "actor": "Jordan", "action": "send", "due": "2026-09-16"},
    {"text": "Noor confirmed she will present the roadmap at the all-hands.", "kind": "commitment", "actor": "Noor", "action": "present", "due": None},
    {"text": "Kenji is going to run the accessibility audit next Monday.", "kind": "commitment", "actor": "Kenji", "action": "run", "due": "2026-09-21"},
    # --- requests
    {"text": "Could you send me the Q3 numbers by Wednesday?", "kind": "request", "actor": "ADDRESSEE", "action": "send", "due": "2026-09-16"},
    {"text": "Please review the attached contract before our call.", "kind": "request", "actor": "ADDRESSEE", "action": "review", "due": None},
    {"text": "Can you approve the travel request by end of day?", "kind": "request", "actor": "ADDRESSEE", "action": "approve", "due": "2026-09-15"},
    {"text": "Would you share the design files with the agency?", "kind": "request", "actor": "ADDRESSEE", "action": "share", "due": None},
    {"text": "Tomas, can you schedule the retro for next week?", "kind": "request", "actor": "Tomas", "action": "schedule", "due": "2026-09-27"},
    {"text": "Please send the final quote to procurement by Oct 5.", "kind": "request", "actor": "ADDRESSEE", "action": "send", "due": "2026-10-05"},
    {"text": "Could you please confirm the headcount for dinner?", "kind": "request", "actor": "ADDRESSEE", "action": "confirm", "due": None},
    {"text": "Can you look over the migration plan tomorrow?", "kind": "request", "actor": "ADDRESSEE", "action": "review", "due": "2026-09-16"},
    {"text": "Please prepare a short summary for the board.", "kind": "request", "actor": "ADDRESSEE", "action": "prepare", "due": None},
    # --- hedged intentions (uncertain)
    {"text": "Maybe we can revisit pricing in October.", "kind": "intention", "actor": "SPEAKER", "action": "revisit", "due": "2026-10-31"},
    {"text": "I might be able to join the call on Friday.", "kind": "intention", "actor": "SPEAKER", "action": "join", "due": "2026-09-18"},
    {"text": "Hopefully we'll finish the redesign next month.", "kind": "intention", "actor": "SPEAKER", "action": "finish", "due": "2026-10-31"},
    {"text": "I'll try to send comments sometime this week.", "kind": "intention", "actor": "SPEAKER", "action": "send", "due": "2026-09-20"},
    {"text": "We could probably ship the beta in November.", "kind": "intention", "actor": "SPEAKER", "action": "ship", "due": "2026-11-30"},
    {"text": "If I have time I'll write up the notes.", "kind": "intention", "actor": "SPEAKER", "action": "write", "due": None},
    # --- completed actions (evidence of fulfilment, not commitments)
    {"text": "I sent the report yesterday.", "kind": "completed", "actor": None, "action": None, "due": None},
    {"text": "Attached is the updated pricing sheet.", "kind": "completed", "actor": None, "action": None, "due": None},
    {"text": "Here's the recording from this morning's call.", "kind": "completed", "actor": None, "action": None, "due": None},
    {"text": "We've finished the data migration.", "kind": "completed", "actor": None, "action": None, "due": None},
    {"text": "I have already reviewed the contract.", "kind": "completed", "actor": None, "action": None, "due": None},
    {"text": "Please find attached the signed agreement.", "kind": "completed", "actor": None, "action": None, "due": None},
    {"text": "The security review is complete.", "kind": "completed", "actor": None, "action": None, "due": None},
    {"text": "I've shared the folder with you.", "kind": "completed", "actor": None, "action": None, "due": None},
    # --- none (no actionable statement)
    {"text": "Thanks for the great session today.", "kind": "none", "actor": None, "action": None, "due": None},
    {"text": "The weather in Lisbon was lovely.", "kind": "none", "actor": None, "action": None, "due": None},
    {"text": "Can you believe how fast this quarter went?", "kind": "none", "actor": None, "action": None, "due": None},
    {"text": "I won't be able to attend on Thursday.", "kind": "none", "actor": None, "action": None, "due": None},
    {"text": "We'll be offline during the holidays.", "kind": "none", "actor": None, "action": None, "due": None},
    {"text": "Our team grew to twelve people this year.", "kind": "none", "actor": None, "action": None, "due": None},
    {"text": "Please note the office is closed on Monday.", "kind": "none", "actor": None, "action": None, "due": None},
    {"text": "I think the new logo looks great.", "kind": "none", "actor": None, "action": None, "due": None},
    {"text": "Should we use Kafka or RabbitMQ?", "kind": "none", "actor": None, "action": None, "due": None},
    {"text": "Ines owns the analytics dashboard.", "kind": "none", "actor": None, "action": None, "due": None},
    {"text": "Feel free to reach out with questions.", "kind": "none", "actor": None, "action": None, "due": None},
    {"text": "Let me know if anything is unclear.", "kind": "none", "actor": None, "action": None, "due": None},
]
