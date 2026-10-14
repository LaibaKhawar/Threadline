import pytest
from sqlalchemy import select

from app.agent.runtime import AgentRuntime
from app.agent.tools import REGISTRY, tool
from app.db import models as m


def test_every_tool_declares_permissions() -> None:
    for t in REGISTRY.values():
        man = t.manifest()
        assert man["access"] in ("READ", "WRITE") and man["scope"] and man["sensitivity"] in ("low", "medium", "high")
        if t.access == "write":
            assert t.requires_approval, t.name
    assert {"send_email", "delete_document", "create_task", "draft_email", "modify_calendar"} <= {t.name for t in REGISTRY.values() if t.access == "write"}
    assert REGISTRY["search_email"].access == "read" and not REGISTRY["search_email"].requires_approval


def test_registering_a_write_tool_without_approval_is_rejected() -> None:
    with pytest.raises(ValueError):
        tool("bad_write", "x", access="write", scope="email", requires_approval=False)(lambda ws, pq: None)


def test_write_tools_never_execute_inside_a_run(db, user) -> None:
    rt = AgentRuntime(db, user.id, use_llm=False)
    from app.agent.runtime import PlannedCall
    from app.retrieval.query_parser import ParsedQuery

    run = m.AgentRun(user_id=user.id, question="x")
    db.add(run)
    db.flush()
    rt._run = run
    called = []
    REGISTRY["delete_document"].fn = lambda *a, **k: called.append(1)  # type: ignore[assignment]
    res = rt.execute(PlannedCall("delete_document", {"document_id": "d1"}, "test"), ParsedQuery(raw="x", keywords=""))
    assert called == [] and "requires approval" in res.summary
    prop = db.scalar(select(m.ActionProposal))
    assert prop.status == "pending" and prop.tool == "delete_document"
    tex = db.scalar(select(m.ToolExecution))
    assert tex.status == "proposed" and tex.access == "write"
