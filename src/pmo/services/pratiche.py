"""Logica di dominio delle pratiche: creazione, cronologia eventi, avanzamento di stato."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pmo.db.base import utcnow
from pmo.db.models import (
    FASE_PER_EVENTO,
    FASI_ORDINATE,
    STATI_TERMINALI,
    Cliente,
    Documento,
    Evento,
    Messaggio,
    Pratica,
    Prodotto,
    Sollecito,
    StatoPratica,
    StatoVerifica,
    TipoEvento,
    TipoFonte,
)
from pmo.services.codici import prossimo_codice

log = logging.getLogger(__name__)


def _indice_fase(stato: str) -> int:
    try:
        return FASI_ORDINATE.index(StatoPratica(stato))
    except ValueError:
        return -1


def normalizza_nome(nome: str) -> str:
    return " ".join(nome.lower().split())


def trova_cliente(session: Session, nome: str | None, crea: bool = False) -> Cliente | None:
    """Cerca un cliente per nome o alias (case-insensitive); opzionalmente lo crea."""
    if not nome:
        return None
    chiave = normalizza_nome(nome)
    for cliente in session.scalars(select(Cliente)).all():
        if normalizza_nome(cliente.nome) == chiave:
            return cliente
        if any(normalizza_nome(a) == chiave for a in (cliente.alias or [])):
            return cliente
    if crea:
        cliente = Cliente(nome=nome.strip(), tipo="altro")
        session.add(cliente)
        session.flush()
        return cliente
    return None


def trova_prodotto(session: Session, nome: str | None, crea: bool = False) -> Prodotto | None:
    if not nome:
        return None
    chiave = normalizza_nome(nome)
    for prodotto in session.scalars(select(Prodotto)).all():
        if normalizza_nome(prodotto.nome) == chiave or any(
            normalizza_nome(a) == chiave for a in (prodotto.alias or [])
        ):
            return prodotto
    if crea:
        prodotto = Prodotto(nome=nome.strip())
        session.add(prodotto)
        session.flush()
        return prodotto
    return None


def crea_pratica(
    session: Session,
    titolo: str,
    *,
    descrizione: str = "",
    cliente: Cliente | None = None,
    prodotto: Prodotto | None = None,
    stato: str = StatoPratica.BOZZA,
    origine: str = "manuale",
    stato_verifica: str = StatoVerifica.CONFERMATO,
    account_id: int | None = None,
    responsabile_user_id: int | None = None,
    created_by_user_id: int | None = None,
    data_scadenza: date | None = None,
    riferimenti: dict | None = None,
    importo_stima: Decimal | None = None,
    importo_offerta: Decimal | None = None,
    importo_ordine: Decimal | None = None,
    priorita: str = "media",
    data_apertura: date | None = None,
    stato_dal: datetime | None = None,
) -> Pratica:
    pratica = Pratica(
        codice=prossimo_codice(session),
        titolo=titolo.strip()[:300],
        descrizione=descrizione or "",
        cliente=cliente,
        prodotto=prodotto,
        stato=stato,
        stato_dal=stato_dal or utcnow(),
        origine=origine,
        stato_verifica=stato_verifica,
        account_id=account_id,
        responsabile_user_id=responsabile_user_id,
        created_by_user_id=created_by_user_id,
        data_scadenza=data_scadenza,
        riferimenti=riferimenti or {},
        importo_stima=importo_stima,
        importo_offerta=importo_offerta,
        importo_ordine=importo_ordine,
        priorita=priorita,
        data_apertura=data_apertura or date.today(),
    )
    session.add(pratica)
    session.flush()
    aggiungi_evento(
        session,
        pratica,
        tipo=TipoEvento.NOTA,
        titolo="Pratica creata" + (" (proposta dall'IA)" if origine == "ai" else ""),
        descrizione="",
        fonte_tipo=TipoFonte.SISTEMA,
        stato_verifica=StatoVerifica.CONFERMATO,
        created_by_user_id=created_by_user_id,
        aggiorna_stato=False,
    )
    return pratica


def cambia_stato(
    session: Session,
    pratica: Pratica,
    nuovo_stato: str,
    *,
    motivo: str = "",
    user_id: int | None = None,
    fonte_tipo: str = TipoFonte.MANUALE,
) -> None:
    nuovo_stato = StatoPratica(nuovo_stato).value
    if pratica.stato == nuovo_stato:
        return
    vecchio = pratica.stato
    pratica.stato = nuovo_stato
    pratica.stato_dal = utcnow()
    if nuovo_stato in {s.value for s in STATI_TERMINALI}:
        pratica.data_chiusura = date.today()
    else:
        pratica.data_chiusura = None
    aggiungi_evento(
        session,
        pratica,
        tipo=TipoEvento.CAMBIO_STATO,
        titolo=f"Stato: {vecchio} → {nuovo_stato}",
        descrizione=motivo,
        fonte_tipo=fonte_tipo,
        created_by_user_id=user_id,
        aggiorna_stato=False,
        dati={"da": vecchio, "a": nuovo_stato},
    )


def _avanza_stato_per_evento(session: Session, pratica: Pratica, evento: Evento) -> None:
    """Avanza la fase della pratica se l'evento implica una fase successiva (mai all'indietro)."""
    fase = FASE_PER_EVENTO.get(evento.tipo)
    if fase is None:
        return
    if pratica.stato in {StatoPratica.ANNULLATA, StatoPratica.SOSPESA, StatoPratica.CHIUSA}:
        return
    if _indice_fase(fase) > _indice_fase(pratica.stato):
        vecchio = pratica.stato
        pratica.stato = fase.value
        pratica.stato_dal = evento.data_evento or utcnow()
        session.add(
            Evento(
                pratica_id=pratica.id,
                tipo=TipoEvento.CAMBIO_STATO,
                data_evento=evento.data_evento or utcnow(),
                titolo=f"Stato: {vecchio} → {fase.value}",
                descrizione=f"Avanzamento automatico per evento '{evento.titolo}'",
                fonte_tipo=TipoFonte.SISTEMA,
                stato_verifica=StatoVerifica.CONFERMATO,
                dati={"da": vecchio, "a": fase.value, "evento_id": evento.id},
            )
        )


def _aggiorna_importi_e_riferimenti(session: Session, pratica: Pratica, evento: Evento) -> None:
    importo = evento.importo
    if importo is not None:
        if evento.tipo == TipoEvento.STIMA_INVIATA and pratica.importo_stima is None:
            pratica.importo_stima = importo
        elif evento.tipo in (TipoEvento.OFFERTA_INVIATA, TipoEvento.OFFERTA_ACCETTATA):
            pratica.importo_offerta = importo
        elif evento.tipo == TipoEvento.ORDINE_RICEVUTO:
            pratica.importo_ordine = importo
        elif evento.tipo == TipoEvento.FATTURA_EMESSA:
            totale = session.scalar(
                select(func.coalesce(func.sum(Evento.importo), 0)).where(
                    Evento.pratica_id == pratica.id,
                    Evento.tipo == TipoEvento.FATTURA_EMESSA,
                    Evento.stato_verifica == StatoVerifica.CONFERMATO,
                )
            )
            pratica.importo_fatturato = Decimal(totale or 0)
    if evento.scadenza:
        if pratica.data_scadenza is None or (
            evento.scadenza >= date.today() and evento.scadenza < pratica.data_scadenza
        ):
            pratica.data_scadenza = evento.scadenza
    riferimenti = (evento.dati or {}).get("riferimenti") or {}
    if riferimenti:
        nuovi = dict(pratica.riferimenti or {})
        for chiave, valore in riferimenti.items():
            if valore and not nuovi.get(chiave):
                nuovi[chiave] = valore
        pratica.riferimenti = nuovi


def _in_utc(valore: datetime) -> datetime:
    return valore if valore.tzinfo is not None else valore.replace(tzinfo=UTC)


def _aggiorna_ultimo_evento(pratica: Pratica, evento: Evento) -> None:
    """Data dell'ultima attività reale: conta anche un evento ancora da verificare, ma non quelli di sistema né
    le date future (le scadenze), perché il dato serve a dire da quando la pratica è ferma."""
    if evento.fonte_tipo == TipoFonte.SISTEMA or evento.data_evento is None:
        return
    data = _in_utc(evento.data_evento)
    if data > utcnow():
        return
    if pratica.ultimo_evento_at is None or data > _in_utc(pratica.ultimo_evento_at):
        pratica.ultimo_evento_at = data


def applica_evento(session: Session, pratica: Pratica, evento: Evento) -> None:
    """Effetti di un evento sulla pratica: l'ultima attività sempre, stato, importi e scadenze solo se confermato."""
    if evento.stato_verifica == StatoVerifica.RIFIUTATO:
        return
    _aggiorna_ultimo_evento(pratica, evento)
    if evento.stato_verifica != StatoVerifica.CONFERMATO:
        return
    _aggiorna_importi_e_riferimenti(session, pratica, evento)
    _avanza_stato_per_evento(session, pratica, evento)
    if evento.tipo == TipoEvento.ANNULLAMENTO and evento.fonte_tipo == TipoFonte.MANUALE:
        cambia_stato(session, pratica, StatoPratica.ANNULLATA, motivo=evento.titolo, fonte_tipo=TipoFonte.SISTEMA)


def aggiungi_evento(
    session: Session,
    pratica: Pratica,
    *,
    tipo: str,
    titolo: str,
    descrizione: str = "",
    data_evento: datetime | None = None,
    fonte_tipo: str = TipoFonte.MANUALE,
    fonte_id: str | None = None,
    fonte_url: str | None = None,
    chiave: str | None = None,
    messaggio_id: int | None = None,
    documento_id: int | None = None,
    account_id: int | None = None,
    importo: Decimal | float | None = None,
    scadenza: date | None = None,
    confidenza: float | None = None,
    stato_verifica: str = StatoVerifica.CONFERMATO,
    dati: dict[str, Any] | None = None,
    created_by_user_id: int | None = None,
    aggiorna_stato: bool = True,
) -> Evento:
    """Aggiunge un evento in modo idempotente (per chiave) e, se confermato, lo applica alla pratica."""
    if chiave:
        esistente = session.scalar(select(Evento).where(Evento.chiave == chiave))
        if esistente is not None:
            return esistente
    evento = Evento(
        pratica_id=pratica.id,
        tipo=TipoEvento(tipo).value,
        data_evento=data_evento or utcnow(),
        titolo=titolo.strip()[:300],
        descrizione=descrizione or "",
        fonte_tipo=fonte_tipo,
        fonte_id=fonte_id,
        fonte_url=fonte_url,
        chiave=chiave,
        messaggio_id=messaggio_id,
        documento_id=documento_id,
        account_id=account_id,
        importo=Decimal(str(importo)) if importo is not None else None,
        scadenza=scadenza,
        confidenza=confidenza,
        stato_verifica=stato_verifica,
        dati=dati or {},
        created_by_user_id=created_by_user_id,
    )
    session.add(evento)
    session.flush()
    if aggiorna_stato:
        applica_evento(session, pratica, evento)
    return evento


def ricalcola_date(session: Session) -> dict[str, int]:
    """Riporta le date delle pratiche a quelle delle fonti (mail, documenti, eventi), non a quella dell'importazione.

    - `ultimo_evento_at` per tutte le pratiche: l'attività più recente non di sistema e non nel futuro.
    - `data_apertura` e `stato_dal` solo per le pratiche proposte dall'IA che hanno ancora la data di importazione.
    È idempotente: si può rilanciare in ogni momento.
    """
    adesso = utcnow()
    contatori = {"pratiche": 0, "ultimo_evento": 0, "apertura": 0}
    # senza scritture intermedie: il blocco del database dura solo il tempo del salvataggio finale
    with session.no_autoflush:
        _ricalcola_date_pratiche(session, adesso, contatori)
    session.flush()
    return contatori


def _ricalcola_date_pratiche(session: Session, adesso: datetime, contatori: dict[str, int]) -> None:
    for pratica in session.scalars(select(Pratica)).all():
        contatori["pratiche"] += 1
        date_fonti: list[datetime] = []
        for evento in pratica.eventi:
            if evento.fonte_tipo != TipoFonte.SISTEMA and evento.stato_verifica != StatoVerifica.RIFIUTATO and evento.data_evento:
                date_fonti.append(_in_utc(evento.data_evento))
        for messaggio in pratica.messaggi:
            if messaggio.data:
                date_fonti.append(_in_utc(messaggio.data))
        for documento in pratica.documenti:
            if documento.modified_time:
                date_fonti.append(_in_utc(documento.modified_time))
        passate = [d for d in date_fonti if d <= adesso]
        if not passate:
            continue
        ultima = max(passate)
        if pratica.ultimo_evento_at is None or _in_utc(pratica.ultimo_evento_at) != ultima:
            pratica.ultimo_evento_at = ultima
            contatori["ultimo_evento"] += 1
        importata = pratica.created_at.date() if pratica.created_at else None
        # la data locale e created_at (UTC) possono differire di un giorno a ridosso della mezzanotte
        if pratica.origine == "ai" and importata is not None and abs((pratica.data_apertura - importata).days) <= 1:
            prima = min(passate)
            pratica.data_apertura = prima.date()
            pratica.stato_dal = prima
            contatori["apertura"] += 1


def conferma_evento(session: Session, evento: Evento, user_id: int | None = None) -> None:
    if evento.stato_verifica == StatoVerifica.CONFERMATO:
        return
    evento.stato_verifica = StatoVerifica.CONFERMATO
    evento.dati = {**(evento.dati or {}), "confermato_da": user_id}
    applica_evento(session, evento.pratica, evento)


def rifiuta_evento(session: Session, evento: Evento, user_id: int | None = None) -> None:
    evento.stato_verifica = StatoVerifica.RIFIUTATO
    evento.dati = {**(evento.dati or {}), "rifiutato_da": user_id}


def conferma_pratica(session: Session, pratica: Pratica, user_id: int | None = None, soglia: float = 0.0) -> None:
    """Conferma una pratica proposta dall'IA e gli eventi proposti con confidenza sufficiente."""
    pratica.stato_verifica = StatoVerifica.CONFERMATO
    for evento in list(pratica.eventi):
        if evento.stato_verifica == StatoVerifica.PROPOSTO and (evento.confidenza or 0) >= soglia:
            conferma_evento(session, evento, user_id)
    for messaggio in pratica.messaggi:
        if messaggio.stato == "da_rivedere":
            messaggio.stato = "classificato"
    for documento in pratica.documenti:
        if documento.stato == "da_rivedere":
            documento.stato = "classificato"


def rifiuta_pratica(session: Session, pratica: Pratica, user_id: int | None = None) -> None:
    """Scarta una pratica proposta: i messaggi tornano in revisione, la pratica viene annullata."""
    pratica.stato_verifica = StatoVerifica.RIFIUTATO
    for messaggio in list(pratica.messaggi):
        messaggio.pratica_id = None
        messaggio.link_origine = None
        messaggio.stato = "da_rivedere"
        messaggio.motivo = "Pratica proposta scartata"
    for documento in list(pratica.documenti):
        documento.pratica_id = None
        documento.link_origine = None
        documento.stato = "da_rivedere"
    for sollecito in list(pratica.solleciti):
        session.delete(sollecito)
    cambia_stato(session, pratica, StatoPratica.ANNULLATA, motivo="Proposta scartata", user_id=user_id)


def unisci_pratiche(session: Session, sorgente: Pratica, destinazione: Pratica, user_id: int | None = None) -> None:
    """Sposta eventi, messaggi e documenti della sorgente nella destinazione e annulla la sorgente."""
    if sorgente.id == destinazione.id:
        return
    for evento in list(sorgente.eventi):
        if evento.tipo in (TipoEvento.CAMBIO_STATO,) and evento.fonte_tipo == TipoFonte.SISTEMA:
            session.delete(evento)
            continue
        evento.pratica_id = destinazione.id
        if evento.chiave:
            evento.chiave = f"{evento.chiave}#merge{sorgente.id}"
        if evento.stato_verifica == StatoVerifica.CONFERMATO:
            applica_evento(session, destinazione, evento)
    for messaggio in session.scalars(select(Messaggio).where(Messaggio.pratica_id == sorgente.id)):
        messaggio.pratica_id = destinazione.id
    for documento in session.scalars(select(Documento).where(Documento.pratica_id == sorgente.id)):
        documento.pratica_id = destinazione.id
    for sollecito in session.scalars(select(Sollecito).where(Sollecito.pratica_id == sorgente.id)):
        session.delete(sollecito)
    for campo in ("importo_stima", "importo_offerta", "importo_ordine", "importo_fatturato"):
        if getattr(destinazione, campo) is None and getattr(sorgente, campo) is not None:
            setattr(destinazione, campo, getattr(sorgente, campo))
    riferimenti = dict(destinazione.riferimenti or {})
    for chiave, valore in (sorgente.riferimenti or {}).items():
        riferimenti.setdefault(chiave, valore)
    destinazione.riferimenti = riferimenti
    if destinazione.data_scadenza is None:
        destinazione.data_scadenza = sorgente.data_scadenza
    session.flush()
    session.refresh(sorgente)
    cambia_stato(
        session,
        sorgente,
        StatoPratica.ANNULLATA,
        motivo=f"Unita alla pratica {destinazione.codice}",
        user_id=user_id,
    )
    aggiungi_evento(
        session,
        destinazione,
        tipo=TipoEvento.NOTA,
        titolo=f"Unita la pratica {sorgente.codice} ({sorgente.titolo})",
        fonte_tipo=TipoFonte.SISTEMA,
        created_by_user_id=user_id,
        aggiorna_stato=False,
    )


def trova_per_codice(session: Session, codice: str | None) -> Pratica | None:
    if not codice:
        return None
    return session.scalar(select(Pratica).where(Pratica.codice == codice.upper()))
