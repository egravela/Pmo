"""Il limite di richieste di Gmail (403 rateLimitExceeded) deve essere ritentato, non scartare il messaggio."""

from __future__ import annotations

import json

import httplib2
from googleapiclient.errors import HttpError

from pmo.connectors import gmail
from pmo.connectors.gmail import GmailClient


def _errore(status: int, reason: str) -> HttpError:
    corpo = json.dumps({"error": {"errors": [{"reason": reason}]}}).encode()
    return HttpError(httplib2.Response({"status": str(status)}), corpo)


class _Richiesta:
    def __init__(self, esiti):
        self.esiti = esiti

    def execute(self):
        esito = self.esiti.pop(0)
        if isinstance(esito, Exception):
            raise esito
        return esito


class _Servizio:
    def __init__(self, esiti):
        self.esiti = esiti
        self.chiamate = 0

    def users(self):
        return self

    def messages(self):
        return self

    def get(self, **kwargs):  # noqa: ARG002
        self.chiamate += 1
        return _Richiesta(self.esiti)


def _client(esiti) -> tuple[GmailClient, _Servizio]:
    client = GmailClient.__new__(GmailClient)
    client.service = _Servizio(esiti)
    return client, client.service


def test_403_rate_limit_viene_ritentato(monkeypatch):
    monkeypatch.setattr(gmail.time, "sleep", lambda _s: None)
    client, servizio = _client([_errore(403, "rateLimitExceeded"), _errore(403, "userRateLimitExceeded"), {"id": "m1"}])
    assert client._get_single("m1", "full") == {"id": "m1"}
    assert servizio.chiamate == 3


def test_403_permessi_non_viene_ritentato(monkeypatch):
    monkeypatch.setattr(gmail.time, "sleep", lambda _s: None)
    client, servizio = _client([_errore(403, "insufficientPermissions"), {"id": "m1"}])
    assert client._get_single("m1", "full") is None
    assert servizio.chiamate == 1


def test_404_restituisce_none(monkeypatch):
    monkeypatch.setattr(gmail.time, "sleep", lambda _s: None)
    client, servizio = _client([_errore(404, "notFound")])
    assert client._get_single("m1", "full") is None
    assert servizio.chiamate == 1
