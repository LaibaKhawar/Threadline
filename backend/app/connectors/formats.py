"""Parsers for local email (.eml / .mbox) and calendar (.ics) files."""

from __future__ import annotations

import email
import email.policy
import hashlib
import mailbox
import re
from datetime import UTC, datetime, timedelta
from email.utils import getaddresses, parsedate_to_datetime

from app.connectors.base import NormalizedEmail, NormalizedEvent


def _addr_list(value: str | None) -> list[dict[str, str]]:
    return [{"name": n or "", "email": a.lower()} for n, a in getaddresses([value or ""]) if a]


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", html)
    text = re.sub(r"<[^>]+>", "", html)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_eml(raw: bytes, external_id: str | None = None) -> NormalizedEmail:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    body, attachments = "", []
    if msg.is_multipart():
        for part in msg.walk():
            disp = part.get_content_disposition()
            if disp == "attachment" or (part.get_filename() and disp != "inline"):
                attachments.append({"filename": part.get_filename() or "attachment", "mime_type": part.get_content_type(),
                                    "size": len(part.get_payload(decode=True) or b"")})
            elif part.get_content_type() == "text/plain" and not body:
                body = part.get_content()
            elif part.get_content_type() == "text/html" and not body:
                body = _html_to_text(part.get_content())
    else:
        body = msg.get_content() if msg.get_content_type() == "text/plain" else _html_to_text(str(msg.get_content()))
    try:
        sent = parsedate_to_datetime(msg["Date"]) if msg["Date"] else datetime.now(UTC)
    except (TypeError, ValueError):
        sent = datetime.now(UTC)
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=UTC)
    frm = _addr_list(msg["From"])
    mid = (msg["Message-ID"] or "").strip() or f"<{hashlib.sha256(raw).hexdigest()[:24]}@local>"
    refs = re.findall(r"<[^>]+>", msg["References"] or "")
    return NormalizedEmail(
        external_id=external_id or mid, message_id=mid, subject=str(msg["Subject"] or "(no subject)"), body=body or "",
        from_addr=frm[0]["email"] if frm else "unknown@unknown", from_name=frm[0]["name"] if frm else None,
        to=_addr_list(msg["To"]), cc=_addr_list(msg["Cc"]), sent_at=sent,
        in_reply_to=(msg["In-Reply-To"] or "").strip() or None, references=refs, attachments=attachments,
    )


def parse_mbox(path: str) -> list[NormalizedEmail]:
    out = []
    for i, msg in enumerate(mailbox.mbox(path)):
        raw = msg.as_bytes()
        out.append(parse_eml(raw, external_id=(msg["Message-ID"] or f"mbox-{i}").strip()))
    return out


def parse_ics(raw: bytes) -> list[NormalizedEvent]:
    from icalendar import Calendar

    cal = Calendar.from_ical(raw)
    out = []
    for comp in cal.walk("VEVENT"):
        start = comp.decoded("DTSTART")
        end = comp.decoded("DTEND") if comp.get("DTEND") else None
        if not isinstance(start, datetime):
            start = datetime(start.year, start.month, start.day, tzinfo=UTC)
        if end is not None and not isinstance(end, datetime):
            end = datetime(end.year, end.month, end.day, tzinfo=UTC)
        start = start if start.tzinfo else start.replace(tzinfo=UTC)
        end = (end if end and end.tzinfo else (end.replace(tzinfo=UTC) if end else start + timedelta(hours=1)))
        attendees = []
        raw_att = comp.get("ATTENDEE")
        for a in (raw_att if isinstance(raw_att, list) else [raw_att] if raw_att else []):
            addr = str(a).replace("mailto:", "").replace("MAILTO:", "")
            attendees.append({"email": addr.lower(), "name": str(a.params.get("CN", "")) if hasattr(a, "params") else ""})
        org = comp.get("ORGANIZER")
        out.append(NormalizedEvent(
            external_id=str(comp.get("UID") or hashlib.sha256(str(comp.get("SUMMARY")).encode() + str(start).encode()).hexdigest()),
            title=str(comp.get("SUMMARY") or "(untitled)"), start_at=start, end_at=end,
            description=str(comp.get("DESCRIPTION") or "") or None, location=str(comp.get("LOCATION") or "") or None,
            attendees=attendees, organizer=str(org).replace("mailto:", "").lower() if org else None,
            status=str(comp.get("STATUS") or "confirmed").lower(),
        ))
    return out
