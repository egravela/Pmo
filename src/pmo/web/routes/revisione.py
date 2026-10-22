"""Coda di revisione: pratiche proposte, messaggi e documenti da verificare, errori."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from pmo.db.models import Documento, Evento, Messaggio, Pratica, StatoMessaggio, StatoVerifica, User
from pmo.web.deps import get_db, render, utente_corrente

router = APIRouter()


@router.get("/revisione")
def revisione(request: Request, scheda: str = "pratiche", session: Session = Depends(get_db), utente: User = Depends(utente_corrente)):
    pratiche = session.scalars(
        select(Pratica)
        .options(selectinload(Pratica.cliente), selectinload(Pratica.eventi), selectinload(Pratica.messaggi))
        .where(Pratica.stato_verifica == StatoVerifica.PROPOSTO.value)
        .order_by(Pratica.id.desc())
    ).all()
    messaggi = session.scalars(
        select(Messaggio)
        .options(selectinload(Messaggio.pratica))
        .where(Messaggio.stato == StatoMessaggio.DA_RIVEDERE.value)
        .order_by(Messaggio.data.desc())
        .limit(200)
    ).all()
    documenti = session.scalars(
        select(Documento)
        .options(selectinload(Documento.pratica))
        .where(Documento.stato == StatoMessaggio.DA_RIVEDERE.value)
        .order_by(Documento.modified_time.desc())
        .limit(200)
    ).all()
    errori = session.scalars(
        select(Messaggio).where(Messaggio.stato == StatoMessaggio.ERRORE.value).order_by(Messaggio.data.desc()).limit(100)
    ).all()
    eventi_per_messaggio: dict[int, list[Evento]] = {}
    if messaggi:
        for e in session.scalars(select(Evento).where(Evento.messaggio_id.in_([m.id for m in messaggi]))).all():
            eventi_per_messaggio.setdefault(e.messaggio_id, []).append(e)
    pratiche_aperte = session.scalars(
        select(Pratica).where(Pratica.stato_verifica == StatoVerifica.CONFERMATO.value, Pratica.stato.notin_(["chiusa", "annullata"])).order_by(Pratica.codice.desc()).limit(300)
    ).all()
    return render(
        request,
        "revisione.html",
        utente,
        scheda=scheda,
        pratiche=pratiche,
        messaggi=messaggi,
        documenti=documenti,
        errori=errori,
        eventi_per_messaggio=eventi_per_messaggio,
        pratiche_aperte=pratiche_aperte,
    )
