import base64

from pmo.connectors.gmail import gmail_query_finestra, parse_message


def _b64(testo: str) -> str:
    return base64.urlsafe_b64encode(testo.encode()).decode().rstrip("=")


def test_parse_message_multipart_con_allegato():
    raw = {
        "id": "abc123",
        "threadId": "thr1",
        "labelIds": ["INBOX", "IMPORTANT"],
        "internalDate": "1792662859000",
        "snippet": "Ciao Emanuele",
        "historyId": "17589436",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "From", "value": "Rocco Antezza <rantezza@latraccia.it>"},
                {"name": "To", "value": "egravela@latraccia.it"},
                {"name": "Cc", "value": "a@latraccia.it, b@latraccia.it"},
                {"name": "Subject", "value": "Proposta: tracciabilità ordini"},
                {"name": "Message-ID", "value": "<m1@latraccia.it>"},
            ],
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {"mimeType": "text/plain", "body": {"data": _b64("Ciao Emanuele,\r\nproposta in breve.")}},
                        {"mimeType": "text/html", "body": {"data": _b64("<p>Ciao Emanuele,</p>")}},
                    ],
                },
                {"mimeType": "application/pdf", "filename": "ordine.pdf", "body": {"attachmentId": "att1", "size": 1234}},
            ],
        },
    }
    m = parse_message(raw)
    assert m.gmail_message_id == "abc123" and m.gmail_thread_id == "thr1"
    assert m.from_email == "rantezza@latraccia.it" and m.from_name == "Rocco Antezza"
    assert m.to == ["egravela@latraccia.it"] and m.cc == ["a@latraccia.it", "b@latraccia.it"]
    assert m.subject == "Proposta: tracciabilità ordini"
    assert m.body_text == "Ciao Emanuele,\nproposta in breve."
    assert [a.filename for a in m.attachments] == ["ordine.pdf"]
    assert m.attachments[0].attachment_id == "att1"
    assert m.data.year == 2026 and not m.has_list_unsubscribe


def test_parse_message_solo_html():
    raw = {
        "id": "x",
        "threadId": "t",
        "internalDate": "0",
        "payload": {
            "mimeType": "text/html",
            "headers": [{"name": "From", "value": "noreply@shop.it"}, {"name": "List-Unsubscribe", "value": "<mailto:x>"}],
            "body": {"data": _b64("<div>Il tuo <b>ordine</b> è partito</div>")},
        },
    }
    m = parse_message(raw)
    assert m.body_text == "Il tuo ordine è partito"
    assert m.has_list_unsubscribe


def test_query_finestra():
    from datetime import UTC, datetime

    q = gmail_query_finestra(datetime(2026, 7, 1, tzinfo=UTC), "-label:personale")
    assert q.startswith("after:2026/07/01 ") and "-category:promotions" in q and q.endswith("-label:personale")
