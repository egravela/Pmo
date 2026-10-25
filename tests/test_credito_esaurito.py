"""Credito Anthropic esaurito: non è colpa dei messaggi, quindi non devono finire in errore."""

from __future__ import annotations

import anthropic
import httpx2
import pytest
from tests.test_classificazione import _account, _messaggio

from pmo.config import Settings
from pmo.db.models import StatoMessaggio
from pmo.ingest.catalogo import carica_catalogo
from pmo.ingest.classifier import ClassificatoreClaude, ErroreClassificazione
from pmo.ingest.gmail_sync import classifica_messaggi
from pmo.ingest.serie_errori import SERIE_ERRORI_MAX


def _errore_400(testo: str) -> anthropic.BadRequestError:
    richiesta = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    risposta = httpx2.Response(400, request=richiesta)
    return anthropic.BadRequestError(testo, response=risposta, body=None)


class _ClienteSenzaCredito:
    def __init__(self, testo: str):
        self.chiamate = 0
        self.beta = self
        self.messages = self
        self._testo = testo

    def parse(self, **kwargs):  # noqa: ARG002
        self.chiamate += 1
        raise _errore_400(self._testo)


def _classificatore(testo: str) -> tuple[ClassificatoreClaude, _ClienteSenzaCredito]:
    cliente = _ClienteSenzaCredito(testo)
    return ClassificatoreClaude(Settings(_env_file=None, anthropic_api_key="x"), client=cliente), cliente


def test_credito_esaurito_e_un_errore_temporaneo():
    classificatore, _ = _classificatore("Your credit balance is too low to access the Anthropic API.")
    with pytest.raises(ErroreClassificazione) as exc:
        classificatore.classifica_thread("catalogo", "prompt")
    assert exc.value.temporaneo is True
    assert "Credito Anthropic esaurito" in str(exc.value)


def test_altra_richiesta_non_valida_resta_definitiva():
    classificatore, _ = _classificatore("max_tokens: Field required")
    with pytest.raises(ErroreClassificazione) as exc:
        classificatore.classifica_thread("catalogo", "prompt")
    assert exc.value.temporaneo is False


def test_senza_credito_il_giro_si_ferma_e_i_messaggi_restano_in_coda(db, settings):
    acc = _account(db)
    messaggi = [_messaggio(db, acc, f"c{i}", f"tc{i}", "Offerta", "testo") for i in range(SERIE_ERRORI_MAX + 5)]
    classificatore, cliente = _classificatore("Your credit balance is too low to access the Anthropic API.")
    run = classifica_messaggi(db, acc, settings, classificatore=classificatore, catalogo=carica_catalogo(db, settings))
    assert cliente.chiamate == SERIE_ERRORI_MAX  # non si insiste con tutte le altre richieste
    assert run.stato == "errore"
    assert all(m.stato == StatoMessaggio.NUOVO for m in messaggi)
