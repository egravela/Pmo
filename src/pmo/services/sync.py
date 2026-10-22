"""Orchestrazione della sincronizzazione: caselle → classificazione → regole."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime

from sqlalchemy import select

from pmo.config import Settings, get_settings
from pmo.db.models import Account
from pmo.db.session import session_scope
from pmo.ingest.catalogo import carica_catalogo
from pmo.ingest.classifier import crea_classificatore
from pmo.ingest.drive_sync import classifica_documenti, sincronizza_drive
from pmo.ingest.gmail_sync import classifica_messaggi, sincronizza_gmail
from pmo.rules.engine import esegui_regole

log = logging.getLogger(__name__)

_lock_globale = threading.Lock()
_in_corso: dict[int, datetime] = {}


def account_in_sincronizzazione(account_id: int) -> bool:
    return account_id in _in_corso


def sincronizza_account(
    account_id: int,
    settings: Settings | None = None,
    *,
    completa: bool = False,
    giorni: int | None = None,
    classifica: bool = True,
    gmail: bool = True,
    drive: bool = True,
) -> dict:
    """Sincronizza una casella (Gmail e Drive) e classifica gli elementi nuovi."""
    settings = settings or get_settings()
    with _lock_globale:
        if account_id in _in_corso:
            return {"saltato": True, "motivo": "sincronizzazione già in corso"}
        _in_corso[account_id] = datetime.now(UTC)
    esito: dict = {}
    try:
        with session_scope() as session:
            account = session.get(Account, account_id)
            if account is None or not account.attivo or not account.collegato:
                return {"saltato": True, "motivo": "casella non attiva o non collegata"}
            if gmail and account.sync_gmail:
                run = sincronizza_gmail(session, account, settings, completa=completa, giorni=giorni)
                esito["gmail"] = {"stato": run.stato, **run.contatori, "errori": run.errori}
            if drive and account.sync_drive and account.watched_folders:
                run = sincronizza_drive(session, account, settings, completa=completa)
                esito["drive"] = {"stato": run.stato, **run.contatori, "errori": run.errori}
            if classifica:
                classificatore = crea_classificatore(settings)
                catalogo = carica_catalogo(session, settings)
                run = classifica_messaggi(session, account, settings, classificatore=classificatore, catalogo=catalogo)
                esito["classificazione_mail"] = {"stato": run.stato, **run.contatori, "errori": run.errori[:5]}
                run = classifica_documenti(session, account, settings, classificatore=classificatore, catalogo=catalogo)
                esito["classificazione_drive"] = {"stato": run.stato, **run.contatori, "errori": run.errori[:5]}
    finally:
        with _lock_globale:
            _in_corso.pop(account_id, None)
    return esito


def sincronizza_tutto(settings: Settings | None = None, *, classifica: bool = True, regole: bool = True, **kwargs) -> dict:
    settings = settings or get_settings()
    with session_scope() as session:
        ids = [a.id for a in session.scalars(select(Account).where(Account.attivo.is_(True))).all() if a.collegato]
    esiti: dict = {}
    for account_id in ids:
        try:
            esiti[account_id] = sincronizza_account(account_id, settings, classifica=classifica, **kwargs)
        except Exception as exc:  # noqa: BLE001
            log.exception("Sincronizzazione fallita per account %s", account_id)
            esiti[account_id] = {"errore": str(exc)}
    if regole:
        esiti["regole"] = esegui_regole_tutto()
    return esiti


def esegui_regole_tutto() -> dict:
    with session_scope() as session:
        run = esegui_regole(session)
        return dict(run.contatori)
