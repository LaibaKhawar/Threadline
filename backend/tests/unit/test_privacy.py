import pytest
from sqlalchemy import select

from app.ai.llm.base import LLMMessage
from app.ai.llm.gateway import LLMGateway, set_provider_override
from app.core.config import get_settings
from app.core.errors import PrivacyViolation
from app.db import models as m
from app.privacy.policy import PrivacyPolicy
from tests.fakes import ScriptedProvider


@pytest.fixture
def providers(monkeypatch):  # type: ignore[no-untyped-def]
    local, cloud = ScriptedProvider("local-fake", "local", fn=lambda _: "ok"), ScriptedProvider("cloud-fake", "cloud", fn=lambda _: "ok")
    set_provider_override("local", local)
    set_provider_override("cloud", cloud)
    s = get_settings()
    monkeypatch.setattr(s, "cloud_base_url", "https://example.invalid/v1")
    monkeypatch.setattr(s, "cloud_model", "cloud-model")
    return local, cloud


def _source(db, user, *, cloud: bool, local: bool = True) -> str:  # type: ignore[no-untyped-def]
    i = m.Integration(user_id=user.id, kind="gmail", name="Gmail", local_ai_allowed=local, cloud_ai_allowed=cloud)
    db.add(i)
    db.flush()
    return i.id


def _call(db, user, iid: str, op: str = "answer_synthesis") -> str:  # type: ignore[no-untyped-def]
    return LLMGateway(db, user.id).complete(op, [LLMMessage("user", "hi")], integration_ids={iid}).provider


def test_local_mode_never_calls_cloud(db, user, providers) -> None:
    local, cloud = providers
    iid = _source(db, user, cloud=True)
    st = db.get(m.UserSettings, user.id)
    st.ai_mode = "LOCAL"
    for op in ("answer_synthesis", "extraction", "meeting_brief"):
        assert _call(db, user, iid, op) == "local-fake"
    assert cloud.calls == [] and len(local.calls) == 3
    assert {c.locality for c in db.scalars(select(m.LLMCall))} == {"local"}


def test_hybrid_requires_allow_listed_operation_and_cloud_permitted_sources(db, user, providers) -> None:
    _, cloud = providers
    ok_src, private_src = _source(db, user, cloud=True), _source(db, user, cloud=False)
    st = db.get(m.UserSettings, user.id)
    st.ai_mode, st.cloud_allowed_operations = "HYBRID", ["meeting_brief"]
    assert _call(db, user, ok_src, "answer_synthesis") == "local-fake"  # not allow-listed
    assert _call(db, user, private_src, "meeting_brief") == "local-fake"  # source forbids cloud
    assert _call(db, user, ok_src, "meeting_brief") == "cloud-fake"
    assert len(cloud.calls) == 1


def test_cloud_mode_still_respects_per_source_settings(db, user, providers) -> None:
    st = db.get(m.UserSettings, user.id)
    st.ai_mode = "CLOUD"
    assert _call(db, user, _source(db, user, cloud=False)) == "local-fake"
    assert _call(db, user, _source(db, user, cloud=True)) == "cloud-fake"


def test_sources_without_local_ai_permission_are_refused(db, user, providers) -> None:
    iid = _source(db, user, cloud=False, local=False)
    with pytest.raises(PrivacyViolation):
        _call(db, user, iid)
    pol = PrivacyPolicy(db, user.id)
    kept, dropped = pol.filter_for_prompt([{"integration_id": iid}, {"integration_id": None}], "local")
    assert dropped == 1 and kept == [{"integration_id": None}]


def test_cloud_unconfigured_falls_back_to_local(db, user, monkeypatch) -> None:
    local = ScriptedProvider("local-fake", "local", fn=lambda _: "ok")
    set_provider_override("local", local)
    monkeypatch.setattr(get_settings(), "cloud_base_url", "")
    st = db.get(m.UserSettings, user.id)
    st.ai_mode = "CLOUD"
    assert _call(db, user, _source(db, user, cloud=True)) == "local-fake"
