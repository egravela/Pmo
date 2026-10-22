"""Applica i risultati della classificazione: collega messaggi e documenti alle pratiche e crea gli eventi."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from pmo.config import Settings, get_settings
from pmo.db.base import utcnow
from pmo.db.models import (
    Documento,
    Messaggio,
    Pratica,
    StatoMessaggio,
    StatoPratica,
    StatoVerifica,
    TipoEvento,
    TipoFonte,
)
from pmo.ingest.catalogo import Catalogo
from pmo.ingest.classifier import (
    EventoEstratto,
    PraticaProposta,
    RiferimentoEstratto,
    RisultatoDocumento,
    RisultatoMessaggio,
)
from pmo.services import pratiche as svc
from pmo.services.pratiche import normalizza_nome

log = logging.getLogger(__name__)


def _parse_date(valore: str | None) -> date | None:
    if not valore:
        return None
    try:
        return date.fromisoformat(valore[:10])
    except ValueError:
        return None


def _data_evento(valore: str | None, fallback: datetime) -> datetime:
    giorno = _parse_date(valore)
    if giorno is None:
        return fallback
    return datetime.combine(giorno, time(12, 0), tzinfo=UTC)


def _riferimenti_dict(riferimenti: list[RiferimentoEstratto]) -> dict[str, str]:
    out: dict[str, str] = {}
    for r in riferimenti or []:
        if r.valore and r.valore.strip():
            chiave = r.chiave if r.chiave != "altro" else f"altro_{len(out) + 1}"
            out.setdefault(chiave, r.valore.strip()[:120])
    return out


def _pratica_proposta_simile(session: Session, proposta: PraticaProposta) -> Pratica | None:
    """Evita doppioni: una pratica proposta dall'IA con lo stesso titolo negli ultimi giorni."""
    chiave = normalizza_nome(proposta.titolo)
    candidati = session.scalars(
        select(Pratica)
        .where(Pratica.origine == "ai", Pratica.stato != StatoPratica.ANNULLATA.value)
        .order_by(Pratica.id.desc())
        .limit(300)
    ).all()
    for pratica in candidati:
        if normalizza_nome(pratica.titolo) == chiave:
            return pratica
    return None


def crea_pratica_proposta(
    session: Session,
    proposta: PraticaProposta,
    catalogo: Catalogo,
    *,
    account_id: int | None,
    cliente_hint_email: str | None = None,
    riferimenti: dict | None = None,
) -> Pratica:
    esistente = _pratica_proposta_simile(session, proposta)
    if esistente is not None:
        return esistente
    cliente = svc.trova_cliente(session, proposta.cliente, crea=False)
    if cliente is None and cliente_hint_email:
        cliente = catalogo.cliente_per_dominio(cliente_hint_email)
    if cliente is None and proposta.cliente:
        cliente = svc.trova_cliente(session, proposta.cliente, crea=True)
        if cliente is not None:
            cliente.note = "Creato automaticamente dall'IA: verificare nome, alias e domini."
    prodotto = svc.trova_prodotto(session, proposta.prodotto, crea=False)
    try:
        stato = StatoPratica(proposta.stato_iniziale).value
    except ValueError:
        stato = StatoPratica.BOZZA.value
    pratica = svc.crea_pratica(
        session,
        proposta.titolo,
        descrizione=proposta.descrizione or "",
        cliente=cliente,
        prodotto=prodotto,
        stato=stato,
        origine="ai",
        stato_verifica=StatoVerifica.PROPOSTO,
        account_id=account_id,
        riferimenti=riferimenti or {},
    )
    catalogo.pratiche.insert(0, pratica)
    return pratica


def _aggiungi_eventi(
    session: Session,
    pratica: Pratica,
    eventi: list[EventoEstratto],
    *,
    chiave_base: str,
    fonte_tipo: str,
    fonte_id: str,
    fonte_url: str | None,
    data_fallback: datetime,
    account_id: int | None,
    messaggio_id: int | None = None,
    documento_id: int | None = None,
    collegamento_sicuro: bool,
    riferimenti: dict | None,
    settings: Settings,
) -> int:
    creati = 0
    contatore: dict[str, int] = {}
    for ev in eventi or []:
        try:
            tipo = TipoEvento(ev.tipo).value
        except ValueError:
            tipo = TipoEvento.ALTRO.value
        n = contatore.get(tipo, 0)
        contatore[tipo] = n + 1
        chiave = f"{chiave_base}:{tipo}" + (f"#{n}" if n else "")
        confermato = (
            collegamento_sicuro
            and pratica.stato_verifica == StatoVerifica.CONFERMATO
            and (ev.confidenza or 0) >= settings.event_confidence_threshold
        )
        evento = svc.aggiungi_evento(
            session,
            pratica,
            tipo=tipo,
            titolo=ev.titolo or tipo,
            descrizione=ev.descrizione or "",
            data_evento=_data_evento(ev.data, data_fallback),
            fonte_tipo=fonte_tipo,
            fonte_id=fonte_id,
            fonte_url=fonte_url,
            chiave=chiave,
            messaggio_id=messaggio_id,
            documento_id=documento_id,
            account_id=account_id,
            importo=ev.importo_eur,
            scadenza=_parse_date(ev.scadenza),
            confidenza=ev.confidenza,
            stato_verifica=StatoVerifica.CONFERMATO if confermato else StatoVerifica.PROPOSTO,
            dati={"riferimenti": riferimenti or {}, "ai": True},
        )
        if evento.created_at and evento.chiave == chiave:
            creati += 1
    return creati


def _risolvi_pratica(
    session: Session,
    catalogo: Catalogo,
    risultato,  # RisultatoMessaggio | RisultatoDocumento
    *,
    pratica_prelinkata: Pratica | None,
    account_id: int | None,
    cliente_hint_email: str | None,
    riferimenti: dict,
    settings: Settings,
) -> tuple[Pratica | None, str | None, bool]:
    """Restituisce (pratica, origine del collegamento, collegamento sicuro)."""
    if pratica_prelinkata is not None:
        return pratica_prelinkata, None, True
    if risultato.collegamento == "esistente" and risultato.pratica_codice:
        pratica = catalogo.pratica_per_codice(risultato.pratica_codice) or svc.trova_per_codice(
            session, risultato.pratica_codice
        )
        if pratica is not None:
            sicuro = (risultato.confidenza_collegamento or 0) >= settings.link_confidence_threshold
            return pratica, "ai", sicuro
    if risultato.collegamento == "nuova" and risultato.pratica_nuova is not None:
        pratica = crea_pratica_proposta(
            session,
            risultato.pratica_nuova,
            catalogo,
            account_id=account_id,
            cliente_hint_email=cliente_hint_email,
            riferimenti=riferimenti,
        )
        return pratica, "ai", False
    return None, None, False


def collega_messaggio(
    session: Session,
    messaggio: Messaggio,
    risultato: RisultatoMessaggio,
    catalogo: Catalogo,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    messaggio.classificazione = risultato.model_dump()
    messaggio.processed_at = utcnow()
    messaggio.confidenza = risultato.confidenza_collegamento
    riferimenti = _riferimenti_dict(risultato.riferimenti)
    prelinkata = messaggio.pratica if messaggio.pratica_id else None

    if not risultato.rilevante and prelinkata is None:
        messaggio.stato = StatoMessaggio.IGNORATO
        messaggio.motivo = f"IA: {risultato.motivo}"[:500]
        return

    cliente_hint = None
    for email in [messaggio.from_email, *messaggio.to_emails, *messaggio.cc_emails]:
        if email and not catalogo.e_interno(email):
            cliente_hint = email
            break

    pratica, origine, sicuro = _risolvi_pratica(
        session,
        catalogo,
        risultato,
        pratica_prelinkata=prelinkata,
        account_id=messaggio.account_id,
        cliente_hint_email=cliente_hint,
        riferimenti=riferimenti,
        settings=settings,
    )
    if pratica is None:
        messaggio.stato = StatoMessaggio.DA_RIVEDERE
        messaggio.motivo = f"IA: pratica non identificata. {risultato.motivo}"[:500]
        return

    messaggio.pratica_id = pratica.id
    if origine:
        messaggio.link_origine = origine
    da_rivedere = (not sicuro) or pratica.stato_verifica != StatoVerifica.CONFERMATO
    messaggio.stato = StatoMessaggio.DA_RIVEDERE if da_rivedere else StatoMessaggio.CLASSIFICATO
    messaggio.motivo = ("IA: " + risultato.motivo)[:500]

    _aggiungi_eventi(
        session,
        pratica,
        risultato.eventi,
        chiave_base=f"email:{messaggio.account_id}:{messaggio.gmail_message_id}",
        fonte_tipo=TipoFonte.EMAIL,
        fonte_id=messaggio.gmail_message_id,
        fonte_url=messaggio.gmail_url,
        data_fallback=messaggio.data,
        account_id=messaggio.account_id,
        messaggio_id=messaggio.id,
        collegamento_sicuro=sicuro,
        riferimenti=riferimenti,
        settings=settings,
    )
    if sicuro and riferimenti and pratica.stato_verifica == StatoVerifica.CONFERMATO:
        nuovi = dict(pratica.riferimenti or {})
        for k, v in riferimenti.items():
            nuovi.setdefault(k, v)
        pratica.riferimenti = nuovi


def collega_documento(
    session: Session,
    documento: Documento,
    risultato: RisultatoDocumento,
    catalogo: Catalogo,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    documento.classificazione = risultato.model_dump()
    documento.processed_at = utcnow()
    documento.confidenza = risultato.confidenza_collegamento
    documento.tipo_documento = risultato.tipo_documento
    riferimenti = _riferimenti_dict(risultato.riferimenti)
    prelinkata = documento.pratica if documento.pratica_id else None

    if not risultato.rilevante and prelinkata is None:
        documento.stato = StatoMessaggio.IGNORATO
        documento.motivo = f"IA: {risultato.motivo}"[:500]
        return

    pratica, origine, sicuro = _risolvi_pratica(
        session,
        catalogo,
        risultato,
        pratica_prelinkata=prelinkata,
        account_id=documento.account_id,
        cliente_hint_email=None,
        riferimenti=riferimenti,
        settings=settings,
    )
    if pratica is None:
        documento.stato = StatoMessaggio.DA_RIVEDERE
        documento.motivo = f"IA: pratica non identificata. {risultato.motivo}"[:500]
        return

    documento.pratica_id = pratica.id
    if origine:
        documento.link_origine = origine
    da_rivedere = (not sicuro) or pratica.stato_verifica != StatoVerifica.CONFERMATO
    documento.stato = StatoMessaggio.DA_RIVEDERE if da_rivedere else StatoMessaggio.CLASSIFICATO
    documento.motivo = ("IA: " + risultato.motivo)[:500]

    eventi = [risultato.evento] if risultato.evento else []
    if not eventi:
        eventi = [
            EventoEstratto(
                tipo="documento",
                data=None,
                titolo=f"Documento: {documento.nome}"[:120],
                descrizione=f"{risultato.tipo_documento} in {documento.percorso or 'Drive'}",
                importo_eur=None,
                scadenza=None,
                confidenza=risultato.confidenza_collegamento,
            )
        ]
    _aggiungi_eventi(
        session,
        pratica,
        eventi,
        chiave_base=f"drive:{documento.account_id}:{documento.drive_file_id}",
        fonte_tipo=TipoFonte.DRIVE,
        fonte_id=documento.drive_file_id,
        fonte_url=documento.web_view_link,
        data_fallback=documento.modified_time or utcnow(),
        account_id=documento.account_id,
        documento_id=documento.id,
        collegamento_sicuro=sicuro,
        riferimenti=riferimenti,
        settings=settings,
    )
