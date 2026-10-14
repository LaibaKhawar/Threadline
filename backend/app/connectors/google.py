"""Gmail and Google Calendar connectors (read-only scopes, incremental sync).

Gmail:    first sync lists recent messages, then uses the History API (cursor = historyId).
          An expired history id (HTTP 404) triggers a bounded full resync.
Calendar: events.list with syncToken (cursor); HTTP 410 means the token expired -> full resync.
          Cancelled events arrive as deletions.
Tokens are refreshed with the stored refresh token; credentials live encrypted in the DB.

These connectors are exercised in tests against recorded-shape HTTP responses (respx). They have not
been run against a live Google account in this repository's test suite (that needs real OAuth client
credentials), which is stated in the README.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from app.connectors.base import (
    Connector,
    ConnectorError,
    Deletion,
    Normalized,
    NormalizedEvent,
    RateLimited,
    SyncContext,
)
from app.connectors.formats import parse_eml
from app.connectors.registry import register

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105  (public endpoint, not a secret)
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
GCAL = "https://www.googleapis.com/calendar/v3/calendars/primary"
SCOPES = {
    "gmail": "https://www.googleapis.com/auth/gmail.readonly",
    "gcal": "https://www.googleapis.com/auth/calendar.readonly",
}


def build_auth_url(client_id: str, redirect_uri: str, kind: str) -> dict[str, str]:
    """Authorization-code + PKCE. The caller stores state and verifier server-side to check the callback."""
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = {"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": SCOPES[kind],
              "access_type": "offline", "prompt": "consent", "state": state, "code_challenge": challenge,
              "code_challenge_method": "S256", "include_granted_scopes": "true"}
    return {"url": f"{AUTH_URL}?{urlencode(params)}", "state": state, "verifier": verifier}


def exchange_code(client_id: str, client_secret: str, redirect_uri: str, code: str, verifier: str) -> dict[str, Any]:
    r = httpx.post(TOKEN_URL, data={"client_id": client_id, "client_secret": client_secret, "code": code,
                                    "code_verifier": verifier, "grant_type": "authorization_code",
                                    "redirect_uri": redirect_uri}, timeout=20)
    if r.status_code != 200:
        raise ConnectorError(f"token exchange failed (HTTP {r.status_code})", retryable=False)
    tok = r.json()
    tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 60
    return tok


class _GoogleBase(Connector):
    requires_network = True
    auth = "oauth2"
    api_kind = "gmail"

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any] | None = None,
                 client: httpx.Client | None = None) -> None:
        super().__init__(config, credentials)
        self._client = client or httpx.Client(timeout=30)
        self.credentials_changed = False

    def _token(self) -> str:
        c = self.credentials
        if not c.get("access_token"):
            raise ConnectorError("not connected: missing access token", retryable=False)
        if c.get("expires_at", 0) < time.time() and c.get("refresh_token"):
            r = self._client.post(TOKEN_URL, data={"client_id": self.config.get("client_id"), "client_secret": self.config.get("client_secret"),
                                                  "refresh_token": c["refresh_token"], "grant_type": "refresh_token"})
            if r.status_code != 200:
                raise ConnectorError("token refresh failed; reconnect the account", retryable=False)
            tok = r.json()
            c["access_token"] = tok["access_token"]
            c["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 60
            self.credentials_changed = True
        return c["access_token"]

    def _get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        for attempt in range(4):
            r = self._client.get(url, params=params, headers={"Authorization": f"Bearer {self._token()}"})
            if "X-RateLimit-Remaining" in r.headers:
                try:
                    self.rate_limit_remaining = int(r.headers["X-RateLimit-Remaining"])
                except ValueError:
                    pass
            if r.status_code == 429 or (r.status_code == 403 and "rateLimitExceeded" in r.text):
                wait = float(r.headers.get("Retry-After", 2 ** attempt))
                if attempt == 3:
                    raise RateLimited(wait)
                time.sleep(min(wait, 30))
                continue
            if r.status_code >= 500:
                if attempt == 3:
                    raise ConnectorError(f"Google API error HTTP {r.status_code}")
                time.sleep(2 ** attempt)
                continue
            return r
        raise ConnectorError("unreachable")

    def authenticate(self) -> dict[str, Any]:
        self._token()
        return {"ok": True}

    def revoke(self) -> None:
        tok = self.credentials.get("refresh_token") or self.credentials.get("access_token")
        if tok:
            self._client.post(REVOKE_URL, data={"token": tok})


@register
class GmailConnector(_GoogleBase):
    kind = "gmail"
    display_name = "Gmail"
    description = "Read-only Gmail sync using the History API for incremental updates."
    item_kinds = ("email",)
    api_kind = "gmail"

    def list_items(self, ctx: SyncContext) -> Iterator[tuple[str, str | None]]:
        if ctx.cursor:
            yield from self._history(ctx.cursor)
            return
        days = int(self.config.get("initial_days", 90))
        page = None
        while True:
            params = {"maxResults": 100, "q": f"newer_than:{days}d"}
            if page:
                params["pageToken"] = page
            r = self._get(f"{GMAIL}/messages", params)
            if r.status_code != 200:
                raise ConnectorError(f"messages.list HTTP {r.status_code}", retryable=r.status_code >= 500)
            data = r.json()
            for msg in data.get("messages", []):
                yield msg["id"], None
            page = data.get("nextPageToken")
            if not page:
                break
        prof = self._get(f"{GMAIL}/profile")
        self.next_cursor = str(prof.json().get("historyId")) if prof.status_code == 200 else None

    def _history(self, start: str) -> Iterator[tuple[str, str | None]]:
        page = None
        self._deleted: list[str] = []
        latest = start
        while True:
            params = {"startHistoryId": start, "historyTypes": ["messageAdded", "messageDeleted"]}
            if page:
                params["pageToken"] = page
            r = self._get(f"{GMAIL}/history", params)
            if r.status_code == 404:  # history expired: fall back to a full listing
                self.next_cursor = None
                yield from self.list_items(SyncContext(cursor=None, checkpoint={}, known={}))
                return
            if r.status_code != 200:
                raise ConnectorError(f"history.list HTTP {r.status_code}")
            data = r.json()
            latest = data.get("historyId", latest)
            for h in data.get("history", []):
                for added in h.get("messagesAdded", []):
                    yield added["message"]["id"], h.get("id")
                for deleted in h.get("messagesDeleted", []):
                    self._deleted.append(deleted["message"]["id"])
            page = data.get("nextPageToken")
            if not page:
                break
        self.next_cursor = str(latest)

    def sync(self, ctx: SyncContext) -> Iterator[Normalized | Deletion]:
        self._deleted = []
        for ext_id, _ in self.list_items(ctx):
            raw = self.get_item(ext_id)
            if raw is None:
                continue
            yield self.normalize(raw)  # type: ignore[misc]
        for d in self._deleted:
            yield Deletion(d)

    def get_item(self, external_id: str) -> dict[str, Any] | None:
        r = self._get(f"{GMAIL}/messages/{external_id}", {"format": "raw"})
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise ConnectorError(f"messages.get HTTP {r.status_code}")
        return r.json()

    def normalize(self, raw: Any) -> Normalized:
        data = base64.urlsafe_b64decode(raw["raw"] + "=" * (-len(raw["raw"]) % 4))
        e = parse_eml(data, external_id=raw["id"])
        e.labels = raw.get("labelIds", [])
        if raw.get("internalDate"):
            e.external_updated_at = datetime.fromtimestamp(int(raw["internalDate"]) / 1000, tz=UTC)
        return e


@register
class GoogleCalendarConnector(_GoogleBase):
    kind = "gcal"
    display_name = "Google Calendar"
    description = "Read-only primary calendar sync with sync tokens."
    item_kinds = ("event",)
    api_kind = "gcal"

    def list_items(self, ctx: SyncContext) -> Iterator[tuple[str, str | None]]:
        raise NotImplementedError  # events arrive in full from the list call; see sync()

    def get_item(self, external_id: str) -> Any:
        r = self._get(f"{GCAL}/events/{external_id}")
        return r.json() if r.status_code == 200 else None

    def sync(self, ctx: SyncContext) -> Iterator[Normalized | Deletion]:
        page = None
        token = ctx.cursor
        while True:
            params: dict[str, Any] = {"singleEvents": "true", "maxResults": 250}
            if token:
                params["syncToken"] = token
            else:
                params["timeMin"] = (datetime.now(UTC) - timedelta(days=int(self.config.get("initial_days", 90)))).isoformat()
            if page:
                params["pageToken"] = page
            r = self._get(f"{GCAL}/events", params)
            if r.status_code == 410 and token:  # sync token expired -> full resync
                token = None
                page = None
                continue
            if r.status_code != 200:
                raise ConnectorError(f"events.list HTTP {r.status_code}")
            data = r.json()
            for item in data.get("items", []):
                if item.get("status") == "cancelled":
                    yield Deletion(item["id"])
                else:
                    yield self.normalize(item)
            page = data.get("nextPageToken")
            if not page:
                self.next_cursor = data.get("nextSyncToken")
                break

    def normalize(self, raw: Any) -> Normalized:
        def dt(v: dict[str, str]) -> datetime:
            if "dateTime" in v:
                return datetime.fromisoformat(v["dateTime"].replace("Z", "+00:00"))
            return datetime.fromisoformat(v["date"]).replace(tzinfo=UTC)

        return NormalizedEvent(
            external_id=raw["id"], title=raw.get("summary", "(untitled)"), start_at=dt(raw["start"]), end_at=dt(raw["end"]),
            description=raw.get("description"), location=raw.get("location"),
            attendees=[{"email": a.get("email", "").lower(), "name": a.get("displayName", ""), "response": a.get("responseStatus", "")}
                       for a in raw.get("attendees", [])],
            organizer=(raw.get("organizer") or {}).get("email"), status=raw.get("status", "confirmed"),
            external_updated_at=datetime.fromisoformat(raw["updated"].replace("Z", "+00:00")) if raw.get("updated") else None,
        )
