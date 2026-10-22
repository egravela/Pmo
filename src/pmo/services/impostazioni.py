"""Impostazioni modificabili dall'interfaccia, salvate nella tabella `impostazioni`."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from pmo.config import Settings, get_settings
from pmo.db.models import Impostazione
from pmo.ingest.filters import (
    DEFAULT_IGNORE_SENDER_PATTERNS,
    DEFAULT_IGNORE_SUBJECT_PATTERNS,
    FiltriRumore,
)

DEFAULTS: dict[str, dict[str, Any]] = {
    "filtri": {
        "ignore_senders": [],
        "ignore_domains": [],
        "keep_senders": [],
        "ignore_sender_patterns": list(DEFAULT_IGNORE_SENDER_PATTERNS),
        "ignore_subject_patterns": list(DEFAULT_IGNORE_SUBJECT_PATTERNS),
    },
    "sync": {"giorni_finestra": None, "max_messaggi": None},
    "digest": {"attivo": True, "destinatari": []},
}


def get_impostazione(session: Session, chiave: str) -> dict[str, Any]:
    riga = session.get(Impostazione, chiave)
    valore = dict(DEFAULTS.get(chiave, {}))
    if riga is not None and isinstance(riga.valore, dict):
        valore.update(riga.valore)
    return valore


def set_impostazione(session: Session, chiave: str, valore: dict[str, Any]) -> None:
    riga = session.get(Impostazione, chiave)
    if riga is None:
        riga = Impostazione(chiave=chiave, valore=valore)
        session.add(riga)
    else:
        riga.valore = valore
    session.flush()


def filtri_rumore(session: Session, settings: Settings | None = None) -> FiltriRumore:
    settings = settings or get_settings()
    cfg = get_impostazione(session, "filtri")
    return FiltriRumore(
        ignore_sender_patterns=list(cfg.get("ignore_sender_patterns") or []),
        ignore_subject_patterns=list(cfg.get("ignore_subject_patterns") or []),
        ignore_senders=[s.lower() for s in cfg.get("ignore_senders") or []],
        ignore_domains=[d.lower() for d in cfg.get("ignore_domains") or []],
        keep_senders=[s.lower() for s in cfg.get("keep_senders") or []],
        internal_domains=list(settings.internal_domains),
    )
