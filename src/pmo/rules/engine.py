"""Motore dei solleciti: valuta le regole su ogni pratica e mantiene aggiornati i solleciti.

Ogni sollecito ha una chiave "<pratica_id>:<regola>": se la condizione persiste il sollecito
viene aggiornato (non duplicato), se cessa viene risolto automaticamente, se era stato risolto
e la condizione si ripresenta viene riaperto.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from pmo.db.base import utcnow
from pmo.db.models import (
    Evento,
    Gravita,
    Pratica,
    Regola,
    Sollecito,
    StatoPratica,
    StatoSollecito,
    StatoVerifica,
    SyncRun,
    TipoEvento,
)
from pmo.rules.definitions import assicura_regole

log = logging.getLogger(__name__)


@dataclass
class Esito:
    regola: str
    gravita: str
    titolo: str
    messaggio: str
    dati: dict = field(default_factory=dict)


def _giorni(da: datetime | None, a: datetime) -> int:
    if da is None:
        return 0
    if da.tzinfo is None:
        da = da.replace(tzinfo=UTC)
    return max(0, (a - da).days)


def _ha_evento(pratica: Pratica, *tipi: str) -> bool:
    return any(e.tipo in tipi and e.stato_verifica == StatoVerifica.CONFERMATO for e in pratica.eventi)


def _eventi_proposti(pratica: Pratica, prima_di: datetime) -> list[Evento]:
    out = []
    for e in pratica.eventi:
        if e.stato_verifica != StatoVerifica.PROPOSTO:
            continue
        creato = e.created_at if e.created_at.tzinfo else e.created_at.replace(tzinfo=UTC)
        if creato <= prima_di:
            out.append(e)
    return out


def valuta_pratica(pratica: Pratica, regole: dict[str, Regola], *, oggi: date, adesso: datetime) -> list[Esito]:
    esiti: list[Esito] = []
    if pratica.stato_verifica == StatoVerifica.RIFIUTATO or pratica.stato == StatoPratica.ANNULLATA:
        return esiti

    def attiva(codice: str) -> Regola | None:
        regola = regole.get(codice)
        return regola if regola is not None and regola.attiva else None

    # Pratiche proposte dall'IA: solo la regola "da_verificare".
    if pratica.stato_verifica == StatoVerifica.PROPOSTO:
        regola = attiva("da_verificare")
        if regola is not None and _giorni(pratica.created_at, adesso) >= (regola.soglia_giorni or 0):
            esiti.append(
                Esito(
                    regola.codice,
                    regola.gravita,
                    "Pratica proposta dall'IA da confermare",
                    f"La pratica è stata proposta dall'IA {_giorni(pratica.created_at, adesso)} giorni fa e attende conferma o scarto.",
                    {"giorni": _giorni(pratica.created_at, adesso)},
                )
            )
        return esiti

    if pratica.stato in (StatoPratica.SOSPESA,):
        return esiti

    giorni_in_stato = _giorni(pratica.stato_dal, adesso)

    regola = attiva("ordine_senza_specifiche")
    if regola and pratica.stato == StatoPratica.ORDINE and giorni_in_stato >= (regola.soglia_giorni or 0):
        if not _ha_evento(pratica, TipoEvento.SPECIFICHE_RICEVUTE, TipoEvento.SPECIFICHE_INVIATE):
            esiti.append(
                Esito(
                    regola.codice,
                    regola.gravita,
                    f"Ordine da {giorni_in_stato} giorni senza specifiche",
                    "L'ordine è stato ricevuto ma non risultano specifiche di integrazione ricevute o inviate: senza specifiche lo sviluppo non può partire.",
                    {"giorni": giorni_in_stato},
                )
            )

    regola = attiva("stima_in_attesa")
    if regola and pratica.stato == StatoPratica.STIMA and giorni_in_stato >= (regola.soglia_giorni or 0):
        if not _ha_evento(pratica, TipoEvento.STIMA_INVIATA, TipoEvento.OFFERTA_INVIATA):
            esiti.append(
                Esito(
                    regola.codice,
                    regola.gravita,
                    f"Stima richiesta da {giorni_in_stato} giorni e non inviata",
                    "È stata richiesta una stima o un preventivo ma non risulta ancora inviato.",
                    {"giorni": giorni_in_stato},
                )
            )

    regola = attiva("offerta_senza_risposta")
    if regola and pratica.stato == StatoPratica.OFFERTA and giorni_in_stato >= (regola.soglia_giorni or 0):
        esiti.append(
            Esito(
                regola.codice,
                regola.gravita,
                f"Offerta senza risposta da {giorni_in_stato} giorni",
                "L'offerta è stata inviata ma non risulta un ordine, un'accettazione o un rifiuto: valutare un sollecito al cliente.",
                {"giorni": giorni_in_stato},
            )
        )

    if pratica.data_scadenza and pratica.stato not in (StatoPratica.CHIUSA,):
        mancanti = (pratica.data_scadenza - oggi).days
        regola = attiva("scadenza_superata")
        if regola and mancanti < 0:
            esiti.append(
                Esito(
                    regola.codice,
                    regola.gravita,
                    f"Scadenza superata da {-mancanti} giorni",
                    f"La scadenza del {pratica.data_scadenza.strftime('%d/%m/%Y')} è passata e la pratica è ancora in stato '{pratica.etichetta_stato}'.",
                    {"scadenza": pratica.data_scadenza.isoformat(), "giorni": -mancanti},
                )
            )
        else:
            regola = attiva("scadenza_vicina")
            if regola and 0 <= mancanti <= (regola.soglia_giorni or 0):
                esiti.append(
                    Esito(
                        regola.codice,
                        regola.gravita,
                        f"Scadenza tra {mancanti} giorni" if mancanti else "Scadenza oggi",
                        f"La pratica scade il {pratica.data_scadenza.strftime('%d/%m/%Y')}.",
                        {"scadenza": pratica.data_scadenza.isoformat(), "giorni": mancanti},
                    )
                )

    regola = attiva("consegnato_non_fatturato")
    if regola and pratica.stato == StatoPratica.CONSEGNA and giorni_in_stato >= (regola.soglia_giorni or 0):
        esiti.append(
            Esito(
                regola.codice,
                regola.gravita,
                f"Consegnato da {giorni_in_stato} giorni e non fatturato",
                "La consegna (o il SAL firmato) risale a più di un mese fa ma non risulta alcuna fattura emessa.",
                {"giorni": giorni_in_stato},
            )
        )

    regola = attiva("fatturato_diverso_da_ordinato")
    if (
        regola
        and pratica.stato in (StatoPratica.FATTURAZIONE, StatoPratica.CHIUSA)
        and pratica.importo_ordine
        and pratica.importo_fatturato is not None
    ):
        parametri = regola.parametri or {}
        toll_pct = Decimal(str(parametri.get("tolleranza_percento", 1.0)))
        toll_eur = Decimal(str(parametri.get("tolleranza_euro", 1.0)))
        tolleranza = max(toll_eur, pratica.importo_ordine * toll_pct / Decimal(100))
        differenza = pratica.importo_fatturato - pratica.importo_ordine
        if abs(differenza) > tolleranza:
            esiti.append(
                Esito(
                    regola.codice,
                    regola.gravita,
                    f"Fatturato {pratica.importo_fatturato:,.2f} € contro ordinato {pratica.importo_ordine:,.2f} €",
                    f"Differenza di {differenza:,.2f} € tra fatturato e ordinato: verificare fatture mancanti o importi errati.",
                    {"differenza": float(differenza)},
                )
            )

    regola = attiva("pratica_inattiva")
    if regola and pratica.stato not in (StatoPratica.CHIUSA,):
        riferimento = pratica.ultimo_evento_at or pratica.stato_dal or pratica.created_at
        fermo = _giorni(riferimento, adesso)
        if fermo >= (regola.soglia_giorni or 0):
            esiti.append(
                Esito(
                    regola.codice,
                    regola.gravita,
                    f"Nessuna attività da {fermo} giorni",
                    f"La pratica è in stato '{pratica.etichetta_stato}' e non registra eventi da {fermo} giorni.",
                    {"giorni": fermo},
                )
            )

    regola = attiva("da_verificare")
    if regola:
        limite = adesso.replace(hour=0, minute=0, second=0, microsecond=0)
        from datetime import timedelta

        proposti = _eventi_proposti(pratica, limite - timedelta(days=regola.soglia_giorni or 0))
        if proposti:
            esiti.append(
                Esito(
                    regola.codice,
                    regola.gravita,
                    f"{len(proposti)} eventi proposti dall'IA da verificare",
                    "Alcuni eventi estratti dall'IA attendono conferma o scarto: finché restano proposti non aggiornano lo stato della pratica.",
                    {"eventi": [e.id for e in proposti]},
                )
            )
    return esiti


def esegui_regole(session: Session, *, oggi: date | None = None, adesso: datetime | None = None) -> SyncRun:
    oggi = oggi or date.today()
    adesso = adesso or utcnow()
    run = SyncRun(tipo="regole")
    session.add(run)
    session.flush()
    regole = assicura_regole(session)
    pratiche = session.scalars(
        select(Pratica).options(selectinload(Pratica.eventi)).where(Pratica.stato_verifica != StatoVerifica.RIFIUTATO.value)
    ).all()
    esistenti = {s.chiave: s for s in session.scalars(select(Sollecito)).all()}
    contatori = {"pratiche": len(pratiche), "nuovi": 0, "riaperti": 0, "aggiornati": 0, "risolti": 0, "attivi": 0}
    chiavi_attive: set[str] = set()
    for pratica in pratiche:
        for esito in valuta_pratica(pratica, regole, oggi=oggi, adesso=adesso):
            chiave = f"{pratica.id}:{esito.regola}"
            chiavi_attive.add(chiave)
            sollecito = esistenti.get(chiave)
            if sollecito is None:
                sollecito = Sollecito(
                    pratica_id=pratica.id,
                    regola=esito.regola,
                    chiave=chiave,
                    gravita=esito.gravita,
                    titolo=esito.titolo[:300],
                    messaggio=esito.messaggio,
                    dati=esito.dati,
                    stato=StatoSollecito.APERTO,
                )
                session.add(sollecito)
                esistenti[chiave] = sollecito
                contatori["nuovi"] += 1
                continue
            sollecito.titolo = esito.titolo[:300]
            sollecito.messaggio = esito.messaggio
            sollecito.dati = esito.dati
            sollecito.gravita = esito.gravita
            if sollecito.stato == StatoSollecito.RISOLTO or (
                sollecito.stato == StatoSollecito.SILENZIATO and sollecito.snooze_fino and sollecito.snooze_fino < oggi
            ):
                sollecito.stato = StatoSollecito.APERTO
                sollecito.aperto_il = adesso
                sollecito.risolto_il = None
                sollecito.risolto_da = None
                sollecito.snooze_fino = None
                sollecito.notificato_il = None
                sollecito.occorrenze = (sollecito.occorrenze or 1) + 1
                contatori["riaperti"] += 1
            else:
                contatori["aggiornati"] += 1
    for chiave, sollecito in esistenti.items():
        if chiave in chiavi_attive:
            if sollecito.stato in (StatoSollecito.APERTO, StatoSollecito.IN_CARICO):
                contatori["attivi"] += 1
            continue
        if sollecito.stato in (StatoSollecito.APERTO, StatoSollecito.IN_CARICO, StatoSollecito.SILENZIATO):
            sollecito.stato = StatoSollecito.RISOLTO
            sollecito.risolto_il = adesso
            sollecito.risolto_da = "sistema"
            contatori["risolti"] += 1
    run.contatori = contatori
    run.stato = "ok"
    run.finished_at = utcnow()
    session.commit()
    return run


def ordina_gravita(gravita: str) -> int:
    return {Gravita.CRITICO: 0, Gravita.AVVISO: 1, Gravita.INFO: 2}.get(gravita, 3)
