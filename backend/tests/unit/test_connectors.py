import base64
import time
from email.message import EmailMessage

import httpx
import respx

from app.connectors.base import Deletion, NormalizedDocument, NormalizedEmail, NormalizedNote, SyncContext
from app.connectors.formats import parse_eml, parse_ics
from app.connectors.google import GmailConnector, GoogleCalendarConnector
from app.connectors.local_files import LocalFilesConnector


def _eml(subject: str = "Hello", body: str = "Hi there") -> bytes:
    msg = EmailMessage()
    msg["From"] = "Sarah Chen <sarah@acme.com>"
    msg["To"] = "Alex <alex@x.com>"
    msg["Subject"] = subject
    msg["Date"] = "Tue, 15 Sep 2026 10:00:00 +0000"
    msg["Message-ID"] = "<m1@acme.com>"
    msg.set_content(body)
    msg.add_attachment(b"data", maintype="application", subtype="pdf", filename="plan.pdf")
    return msg.as_bytes()


def test_parse_eml_and_ics() -> None:
    e = parse_eml(_eml())
    assert (e.from_addr, e.subject, e.attachments[0]["filename"]) == ("sarah@acme.com", "Hello", "plan.pdf")
    ics = (b"BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:ev1\nSUMMARY:Sync\nDTSTART:20261015T110000Z\nDTEND:20261015T113000Z\n"
           b"ATTENDEE;CN=John Park:mailto:john@h.com\nEND:VEVENT\nEND:VCALENDAR\n")
    ev = parse_ics(ics)[0]
    assert ev.title == "Sync" and ev.attendees[0]["email"] == "john@h.com"


def test_local_folder_incremental_sync_and_deletions(tmp_path) -> None:
    (tmp_path / "note.md").write_text("# Plan\nhello")
    (tmp_path / "doc.txt").write_text("text")
    (tmp_path / "mail.eml").write_bytes(_eml())
    (tmp_path / ".hidden.txt").write_text("skip")
    c = LocalFilesConnector({"path": str(tmp_path), "_allowed_roots": [str(tmp_path)]})
    items = list(c.sync(SyncContext(None, {}, {})))
    kinds = sorted(type(i).__name__ for i in items)
    assert kinds == ["NormalizedDocument", "NormalizedEmail", "NormalizedNote"]
    _, cp = c.checkpoint()
    known = {i.external_id: "h" for i in items}
    # unchanged second run: nothing re-read, nothing deleted
    c2 = LocalFilesConnector({"path": str(tmp_path), "_allowed_roots": [str(tmp_path)]})
    assert list(c2.sync(SyncContext(None, cp, known))) == []
    # modify one file and delete another
    time.sleep(0.01)
    (tmp_path / "doc.txt").write_text("changed text")
    (tmp_path / "note.md").unlink()
    c3 = LocalFilesConnector({"path": str(tmp_path), "_allowed_roots": [str(tmp_path)]})
    out = list(c3.sync(SyncContext(None, cp, known)))
    assert any(isinstance(i, NormalizedDocument) and i.content == b"changed text" for i in out)
    assert any(isinstance(i, Deletion) and i.external_id == "note.md" for i in out)
    assert not any(isinstance(i, NormalizedNote) for i in out)


def test_local_folder_respects_allowed_roots(tmp_path) -> None:
    import pytest

    from app.connectors.base import ConnectorError

    with pytest.raises(ConnectorError):
        LocalFilesConnector({"path": str(tmp_path), "_allowed_roots": ["/nonexistent-root"]}).authenticate()


@respx.mock
def test_gmail_initial_then_incremental_sync() -> None:
    raw = base64.urlsafe_b64encode(_eml("Atlas")).decode().rstrip("=")
    respx.get("https://gmail.googleapis.com/gmail/v1/users/me/messages").mock(return_value=httpx.Response(200, json={"messages": [{"id": "g1"}]}))
    respx.get("https://gmail.googleapis.com/gmail/v1/users/me/messages/g1").mock(return_value=httpx.Response(200, json={"id": "g1", "raw": raw, "internalDate": "1789466400000"}))
    respx.get("https://gmail.googleapis.com/gmail/v1/users/me/profile").mock(return_value=httpx.Response(200, json={"historyId": "100"}))
    c = GmailConnector({}, {"access_token": "t", "expires_at": time.time() + 3600})
    items = list(c.sync(SyncContext(None, {}, {})))
    assert isinstance(items[0], NormalizedEmail) and items[0].subject == "Atlas" and c.next_cursor == "100"
    respx.get("https://gmail.googleapis.com/gmail/v1/users/me/history").mock(return_value=httpx.Response(200, json={
        "historyId": "120", "history": [{"id": "110", "messagesDeleted": [{"message": {"id": "g0"}}]}]}))
    c2 = GmailConnector({}, {"access_token": "t", "expires_at": time.time() + 3600})
    out = list(c2.sync(SyncContext("100", {}, {})))
    assert out == [Deletion("g0")] and c2.next_cursor == "120"


@respx.mock
def test_gmail_rate_limit_is_retried(monkeypatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda s: None)
    route = respx.get("https://gmail.googleapis.com/gmail/v1/users/me/profile")
    route.side_effect = [httpx.Response(429, headers={"Retry-After": "1"}), httpx.Response(200, json={"historyId": "5"})]
    c = GmailConnector({}, {"access_token": "t", "expires_at": time.time() + 3600})
    assert c._get("https://gmail.googleapis.com/gmail/v1/users/me/profile").json()["historyId"] == "5"


@respx.mock
def test_gcal_sync_token_expiry_triggers_full_resync() -> None:
    url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    route = respx.get(url)
    route.side_effect = [
        httpx.Response(410),
        httpx.Response(200, json={"items": [{"id": "ev1", "summary": "Sync", "start": {"dateTime": "2026-10-15T11:00:00Z"},
                                            "end": {"dateTime": "2026-10-15T11:30:00Z"}},
                                           {"id": "ev2", "status": "cancelled"}], "nextSyncToken": "tok2"}),
    ]
    c = GoogleCalendarConnector({}, {"access_token": "t", "expires_at": time.time() + 3600})
    out = list(c.sync(SyncContext("expired-token", {}, {})))
    assert out[0].title == "Sync" and out[1] == Deletion("ev2") and c.next_cursor == "tok2"


@respx.mock
def test_expired_token_is_refreshed() -> None:
    respx.post("https://oauth2.googleapis.com/token").mock(return_value=httpx.Response(200, json={"access_token": "new", "expires_in": 3600}))
    c = GmailConnector({"client_id": "c", "client_secret": "s"}, {"access_token": "old", "refresh_token": "r", "expires_at": 0})
    assert c._token() == "new" and c.credentials_changed


def test_local_folder_requires_roots_and_never_reads_the_data_dir(tmp_path) -> None:
    import pytest

    from app.connectors.base import ConnectorError

    with pytest.raises(ConnectorError, match="disabled"):
        LocalFilesConnector({"path": str(tmp_path)}).authenticate()  # no roots configured -> no folder access at all
    data = tmp_path / "data"
    (data / "uploads").mkdir(parents=True)
    with pytest.raises(ConnectorError, match="Threadline's own data"):
        LocalFilesConnector({"path": str(data / "uploads"), "_allowed_roots": [str(tmp_path)], "_forbidden_roots": [str(data)]}).authenticate()
