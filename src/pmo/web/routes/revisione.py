"""Coda di revisione: pratiche proposte, messaggi e documenti da verificare, errori."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from pmo.db.models import Documento, Evento, Messaggio, Pratica, StatoMessaggio, StatoVerifica, User
from pmo.web.deps import get_db, pagina_per, render, utente_corrente

router = APIRouter()


PER_PAGINA = {"pratiche": 24, "messaggi": 20, "documenti": 24, "errori": 30}


@router.get("/revisione")
def revisione(request: Request, scheda: str = "pratiche", session: Session = Depends(get_db), utente: User = Depends(utente_corrente)):
    if scheda not in PER_PAGINA:
        scheda = "pratiche"
    filtri = {
        "pratiche": (Pratica, Pratica.stato_verifica == StatoVerifica.PROPOSTO.value),
        "messaggi": (Messaggio, Messaggio.stato == StatoMessaggio.DA_RIVEDERE.value),
        "documenti": (Documento, Documento.stato == StatoMessaggio.DA_RIVEDERE.value),
        "errori": (Messaggio, Messaggio.stato == StatoMessaggio.ERRORE.value),
    }
    conteggi = {k: session.scalar(select(func.count(m.id)).where(cond)) or 0 for k, (m, cond) in filtri.items()}
    pagina = pagina_per(request, conteggi[scheda], PER_PAGINA[scheda])

    pratiche: list = []
    messaggi: list = []
    documenti: list = []
    errori: list = []
    if scheda == "pratiche":
        pratiche = session.scalars(
            select(Pratica)
            .options(selectinload(Pratica.cliente), selectinload(Pratica.eventi), selectinload(Pratica.messaggi))
            .where(filtri["pratiche"][1])
            .order_by(Pratica.id.desc())
            .offset(pagina.offset)
            .limit(pagina.per_pagina)
        ).all()
    elif scheda == "messaggi":
        messaggi = session.scalars(
            select(Messaggio)
            .options(selectinload(Messaggio.pratica))
            .where(filtri["messaggi"][1])
            .order_by(Messaggio.data.desc())
            .offset(pagina.offset)
            .limit(pagina.per_pagina)
        ).all()
    elif scheda == "documenti":
        documenti = session.scalars(
            select(Documento)
            .options(selectinload(Documento.pratica))
            .where(filtri["documenti"][1])
            .order_by(Documento.modified_time.desc())
            .offset(pagina.offset)
            .limit(pagina.per_pagina)
        ).all()
    else:
        errori = session.scalars(
            select(Messaggio).where(filtri["errori"][1]).order_by(Messaggio.data.desc()).offset(pagina.offset).limit(pagina.per_pagina)
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
        conteggi=conteggi,
        pagina=pagina,
        pratiche=pratiche,
        messaggi=messaggi,
        documenti=documenti,
        errori=errori,
        eventi_per_messaggio=eventi_per_messaggio,
        pratiche_aperte=pratiche_aperte,
    )
