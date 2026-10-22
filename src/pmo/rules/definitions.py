"""Regole di sollecito predefinite (soglie modificabili dall'interfaccia)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from pmo.db.models import Gravita, Regola

REGOLE_DEFAULT: list[dict] = [
    {
        "codice": "ordine_senza_specifiche",
        "nome": "Ordine senza specifiche",
        "descrizione": "La pratica è in stato 'ordine' da più di N giorni senza specifiche ricevute o inviate.",
        "soglia_giorni": 15,
        "gravita": Gravita.AVVISO,
    },
    {
        "codice": "stima_in_attesa",
        "nome": "Stima non inviata",
        "descrizione": "È stata richiesta una stima ma non risulta inviata da più di N giorni.",
        "soglia_giorni": 7,
        "gravita": Gravita.AVVISO,
    },
    {
        "codice": "offerta_senza_risposta",
        "nome": "Offerta senza risposta",
        "descrizione": "Offerta inviata senza ordine o esito da più di N giorni.",
        "soglia_giorni": 30,
        "gravita": Gravita.AVVISO,
    },
    {
        "codice": "scadenza_vicina",
        "nome": "Scadenza vicina",
        "descrizione": "La scadenza della pratica cade entro N giorni.",
        "soglia_giorni": 7,
        "gravita": Gravita.AVVISO,
    },
    {
        "codice": "scadenza_superata",
        "nome": "Scadenza superata",
        "descrizione": "La scadenza della pratica è passata e la pratica non è chiusa.",
        "soglia_giorni": 0,
        "gravita": Gravita.CRITICO,
    },
    {
        "codice": "consegnato_non_fatturato",
        "nome": "Consegnato ma non fatturato",
        "descrizione": "Consegna effettuata o SAL firmato da più di N giorni senza fattura emessa.",
        "soglia_giorni": 30,
        "gravita": Gravita.CRITICO,
    },
    {
        "codice": "fatturato_diverso_da_ordinato",
        "nome": "Fatturato diverso dall'ordinato",
        "descrizione": "L'importo fatturato differisce dall'importo ordinato oltre la tolleranza.",
        "soglia_giorni": None,
        "gravita": Gravita.AVVISO,
        "parametri": {"tolleranza_percento": 1.0, "tolleranza_euro": 1.0},
    },
    {
        "codice": "pratica_inattiva",
        "nome": "Pratica ferma",
        "descrizione": "Nessun evento registrato da più di N giorni su una pratica attiva.",
        "soglia_giorni": 30,
        "gravita": Gravita.INFO,
    },
    {
        "codice": "da_verificare",
        "nome": "Elementi da verificare",
        "descrizione": "Pratica proposta dall'IA o eventi proposti in attesa di conferma da più di N giorni.",
        "soglia_giorni": 3,
        "gravita": Gravita.INFO,
    },
]


def assicura_regole(session: Session) -> dict[str, Regola]:
    """Crea le regole mancanti con i valori predefiniti e restituisce tutte le regole per codice."""
    esistenti = {r.codice: r for r in session.scalars(select(Regola)).all()}
    for spec in REGOLE_DEFAULT:
        if spec["codice"] not in esistenti:
            regola = Regola(
                codice=spec["codice"],
                nome=spec["nome"],
                descrizione=spec["descrizione"],
                soglia_giorni=spec["soglia_giorni"],
                gravita=spec["gravita"],
                attiva=True,
                parametri=spec.get("parametri", {}),
            )
            session.add(regola)
            esistenti[spec["codice"]] = regola
    session.flush()
    return esistenti
