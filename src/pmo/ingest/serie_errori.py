"""Interruzione della classificazione quando a fallire non sono i singoli elementi ma la rete o il servizio IA."""

from __future__ import annotations

from typing import Any

from pmo.db.models import StatoMessaggio

SERIE_ERRORI_MAX = 5  # errori temporanei consecutivi dopo i quali ci si ferma
MOTIVO_INTERRUZIONE = "interrotto: errori temporanei consecutivi (rete o servizio IA non raggiungibili)"


def annulla_tentativi(serie: list[tuple[list[Any], list[Any]]]) -> None:
    """Rimette in coda gli elementi di una serie di errori consecutivi, azzerando il tentativo che hanno consumato.

    `serie` contiene coppie (elementi, classificazioni precedenti). Senza questo passaggio una caduta di rete di
    qualche ora porterebbe in stato "errore" (dopo tre tentativi) messaggi e documenti perfettamente validi.
    """
    for elementi, precedenti in serie:
        for elemento, precedente in zip(elementi, precedenti, strict=True):
            elemento.classificazione = precedente
            elemento.stato = StatoMessaggio.NUOVO
            elemento.motivo = ""
