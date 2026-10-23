"""Client Gmail: ricerca, lettura incrementale (history), parsing dei messaggi, allegati, invio."""

from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from pmo.ingest.filters import html_to_text, normalizza_spazi, parse_addresses

log = logging.getLogger(__name__)

BATCH_SIZE = 10  # Gmail limita le richieste simultanee per utente: lotti più grandi producono 403 rateLimitExceeded


def _limite_richieste(exc: HttpError) -> bool:
    """Gmail segnala il limite di richieste con 429 oppure con 403 (rateLimitExceeded / userRateLimitExceeded)."""
    if exc.resp.status == 429:
        return True
    if exc.resp.status == 403:
        return "ratelimitexceeded" in (exc.content or b"").decode("utf-8", "ignore").lower()
    return False


class HistoryScaduta(Exception):
    """Il historyId è troppo vecchio: serve una sincronizzazione per finestra temporale."""


@dataclass
class Allegato:
    filename: str
    mime_type: str
    size: int
    attachment_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"filename": self.filename, "mime_type": self.mime_type, "size": self.size, "attachment_id": self.attachment_id}


@dataclass
class MessaggioParsato:
    gmail_message_id: str
    gmail_thread_id: str
    labels: list[str]
    subject: str
    from_name: str
    from_email: str
    to: list[str]
    cc: list[str]
    data: datetime
    snippet: str
    body_text: str
    attachments: list[Allegato] = field(default_factory=list)
    message_id_header: str | None = None
    in_reply_to: str | None = None
    has_list_unsubscribe: bool = False
    history_id: str | None = None


def _b64decode(data: str | None) -> bytes:
    if not data:
        return b""
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded)


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for h in payload.get("headers", []) or []:
        nome = (h.get("name") or "").lower()
        if nome and nome not in out:
            out[nome] = h.get("value") or ""
    return out


def _walk_parts(part: dict[str, Any], testo: list[str], html: list[str], allegati: list[Allegato]) -> None:
    mime = (part.get("mimeType") or "").lower()
    filename = part.get("filename") or ""
    body = part.get("body") or {}
    if filename and (body.get("attachmentId") or body.get("data")):
        allegati.append(
            Allegato(
                filename=filename,
                mime_type=mime,
                size=int(body.get("size") or 0),
                attachment_id=body.get("attachmentId"),
            )
        )
        return
    if mime.startswith("multipart/"):
        for sub in part.get("parts", []) or []:
            _walk_parts(sub, testo, html, allegati)
        return
    data = body.get("data")
    if not data:
        for sub in part.get("parts", []) or []:
            _walk_parts(sub, testo, html, allegati)
        return
    contenuto = _b64decode(data).decode("utf-8", errors="replace")
    if mime == "text/plain":
        testo.append(contenuto)
    elif mime == "text/html":
        html.append(contenuto)


def parse_message(raw: dict[str, Any]) -> MessaggioParsato:
    payload = raw.get("payload") or {}
    headers = _headers(payload)
    testo: list[str] = []
    html: list[str] = []
    allegati: list[Allegato] = []
    _walk_parts(payload, testo, html, allegati)
    if testo:
        body = normalizza_spazi("\n".join(testo))
    elif html:
        body = html_to_text("\n".join(html))
    else:
        body = ""
    mittenti = parse_addresses(headers.get("from"))
    from_name, from_email = mittenti[0] if mittenti else ("", "")
    internal_ms = int(raw.get("internalDate") or 0)
    data = datetime.fromtimestamp(internal_ms / 1000, tz=UTC) if internal_ms else datetime.now(UTC)
    return MessaggioParsato(
        gmail_message_id=raw["id"],
        gmail_thread_id=raw.get("threadId") or raw["id"],
        labels=list(raw.get("labelIds") or []),
        subject=headers.get("subject", "").strip(),
        from_name=from_name,
        from_email=from_email,
        to=[e for _, e in parse_addresses(headers.get("to"))],
        cc=[e for _, e in parse_addresses(headers.get("cc"))],
        data=data,
        snippet=raw.get("snippet") or "",
        body_text=body,
        attachments=allegati,
        message_id_header=headers.get("message-id"),
        in_reply_to=headers.get("in-reply-to"),
        has_list_unsubscribe="list-unsubscribe" in headers,
        history_id=raw.get("historyId"),
    )


class GmailClient:
    def __init__(self, credentials):  # noqa: ANN001
        self.service = build("gmail", "v1", credentials=credentials, cache_discovery=False)

    # --- profilo e ricerca ---------------------------------------------------------------------
    def profile(self) -> dict[str, Any]:
        return self.service.users().getProfile(userId="me").execute()

    def list_message_ids(self, query: str, max_results: int = 500) -> list[str]:
        ids: list[str] = []
        page_token = None
        while len(ids) < max_results:
            resp = (
                self.service.users()
                .messages()
                .list(userId="me", q=query, maxResults=min(100, max_results - len(ids)), pageToken=page_token)
                .execute()
            )
            for m in resp.get("messages", []) or []:
                ids.append(m["id"])
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return ids

    def history_new_message_ids(self, start_history_id: str) -> tuple[list[str], str | None]:
        """Messaggi aggiunti dopo start_history_id. Solleva HistoryScaduta se l'id non è più valido."""
        ids: list[str] = []
        latest: str | None = None
        page_token = None
        while True:
            try:
                resp = (
                    self.service.users()
                    .history()
                    .list(
                        userId="me",
                        startHistoryId=start_history_id,
                        historyTypes=["messageAdded"],
                        pageToken=page_token,
                        maxResults=500,
                    )
                    .execute()
                )
            except HttpError as exc:
                if exc.resp.status in (404, 410):
                    raise HistoryScaduta(str(exc)) from exc
                raise
            latest = resp.get("historyId") or latest
            for h in resp.get("history", []) or []:
                for added in h.get("messagesAdded", []) or []:
                    msg = added.get("message") or {}
                    labels = msg.get("labelIds") or []
                    if "DRAFT" in labels:
                        continue
                    if msg.get("id") and msg["id"] not in ids:
                        ids.append(msg["id"])
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return ids, latest

    # --- lettura --------------------------------------------------------------------------------
    def get_messages(self, ids: list[str], fmt: str = "full") -> list[dict[str, Any]]:
        risultati: list[dict[str, Any]] = []
        for i in range(0, len(ids), BATCH_SIZE):
            chunk = ids[i : i + BATCH_SIZE]
            risultati.extend(self._get_batch(chunk, fmt))
        return risultati

    def _get_batch(self, ids: list[str], fmt: str) -> list[dict[str, Any]]:
        ok: dict[str, dict[str, Any]] = {}
        falliti: list[str] = []

        def callback(request_id, response, exception):  # noqa: ANN001
            if exception is not None:
                falliti.append(request_id)
            else:
                ok[request_id] = response

        batch = self.service.new_batch_http_request(callback=callback)
        for mid in ids:
            batch.add(self.service.users().messages().get(userId="me", id=mid, format=fmt), request_id=mid)
        try:
            batch.execute()
        except HttpError as exc:
            log.warning("Batch Gmail fallito (%s): riprovo i messaggi singolarmente", exc)
            falliti = list(ids)
            ok = {}
        for mid in falliti:
            msg = self._get_single(mid, fmt)
            if msg is not None:
                ok[mid] = msg
        return [ok[mid] for mid in ids if mid in ok]

    def _get_single(self, mid: str, fmt: str, tentativi: int = 6) -> dict[str, Any] | None:
        for tentativo in range(tentativi):
            try:
                return self.service.users().messages().get(userId="me", id=mid, format=fmt).execute()
            except HttpError as exc:
                if exc.resp.status == 404:
                    return None
                if (_limite_richieste(exc) or exc.resp.status in (500, 503)) and tentativo < tentativi - 1:
                    time.sleep(min(2**tentativo, 16))
                    continue
                log.error("Errore lettura messaggio %s: %s", mid, exc)
                return None
        return None

    def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
        resp = (
            self.service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute()
        )
        return _b64decode(resp.get("data"))

    # --- invio ----------------------------------------------------------------------------------
    def send_email(self, to: list[str], subject: str, text: str, html: str | None = None, sender: str | None = None) -> str:
        msg = MIMEMultipart("alternative")
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        if sender:
            msg["From"] = sender
        msg.attach(MIMEText(text, "plain", "utf-8"))
        if html:
            msg.attach(MIMEText(html, "html", "utf-8"))
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        resp = self.service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return resp.get("id", "")


def gmail_query_finestra(da: datetime, filtro_extra: str = "") -> str:
    """Query Gmail per la finestra iniziale: esclude spam, cestino, bozze e categorie rumorose."""
    base = f"after:{da.strftime('%Y/%m/%d')} -in:spam -in:trash -in:draft -category:promotions -category:social"
    if filtro_extra:
        base += " " + filtro_extra.strip()
    return base
