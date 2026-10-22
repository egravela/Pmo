"""Solleciti: elenco, presa in carico, risoluzione, silenziamento."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from pmo.db.base import utcnow
from pmo.db.models import Pratica, Regola, Sollecito, StatoSollecito, User
from pmo.rules.engine import ordina_gravita
from pmo.services.sync import esegui_regole_tutto
from pmo.web.deps import flash, get_db, redirect, render, utente_corrente, verifica_csrf

router = APIRouter()


@router.get("/solleciti")
def elenco(
    request: Request,
    stato: str = "aperti",
    gravita: str = "",
    regola: str = "",
    assegnato: str = "",
    session: Session = Depends(get_db),
    utente: User = Depends(utente_corrente),
):
    query = select(Sollecito).options(selectinload(Sollecito.pratica).selectinload(Pratica.cliente), selectinload(Sollecito.assegnato))
    if stato == "aperti":
        query = query.where(Sollecito.stato.in_([StatoSollecito.APERTO.value, StatoSollecito.IN_CARICO.value]))
    elif stato:
        query = query.where(Sollecito.stato == stato)
    if gravita:
        query = query.where(Sollecito.gravita == gravita)
    if regola:
        query = query.where(Sollecito.regola == regola)
    if assegnato == "me":
        query = query.where(Sollecito.assegnato_user_id == utente.id)
    solleciti = session.scalars(query.order_by(Sollecito.aperto_il.desc()).limit(500)).all()
    oggi = date.today()
    if stato == "aperti":
        solleciti = [s for s in solleciti if not (s.snooze_fino and s.snooze_fino > oggi)]
    solleciti.sort(key=lambda s: (ordina_gravita(s.gravita), s.pratica.codice))
    regole = session.scalars(select(Regola).order_by(Regola.nome)).all()
    return render(
        request,
        "solleciti/elenco.html",
        utente,
        solleciti=solleciti,
        regole=regole,
        filtri={"stato": stato, "gravita": gravita, "regola": regola, "assegnato": assegnato},
    )


@router.post("/solleciti/ricalcola", dependencies=[Depends(verifica_csrf)])
def ricalcola(request: Request, utente: User = Depends(utente_corrente)):
    esito = esegui_regole_tutto()
    flash(request, f"Regole eseguite: {esito.get('nuovi', 0)} nuovi, {esito.get('riaperti', 0)} riaperti, {esito.get('risolti', 0)} risolti.")
    return redirect("/solleciti")


@router.post("/solleciti/{sollecito_id}/{azione}", dependencies=[Depends(verifica_csrf)])
def azione(
    request: Request,
    sollecito_id: int,
    azione: str,
    giorni: int = Form(7),
    ritorno: str = Form("/solleciti"),
    session: Session = Depends(get_db),
    utente: User = Depends(utente_corrente),
):
    sollecito = session.get(Sollecito, sollecito_id)
    if sollecito is None:
        raise HTTPException(status_code=404)
    if azione == "prendi":
        sollecito.stato = StatoSollecito.IN_CARICO
        sollecito.assegnato_user_id = utente.id
        flash(request, "Sollecito preso in carico.")
    elif azione == "risolvi":
        sollecito.stato = StatoSollecito.RISOLTO
        sollecito.risolto_il = utcnow()
        sollecito.risolto_da = "utente"
        flash(request, "Sollecito risolto (si riaprirà se la condizione persiste al prossimo controllo).")
    elif azione == "silenzia":
        sollecito.stato = StatoSollecito.SILENZIATO
        sollecito.snooze_fino = date.today() + timedelta(days=max(1, giorni))
        flash(request, f"Sollecito silenziato fino al {sollecito.snooze_fino.strftime('%d/%m/%Y')}.")
    elif azione == "riapri":
        sollecito.stato = StatoSollecito.APERTO
        sollecito.snooze_fino = None
        sollecito.risolto_il = None
        flash(request, "Sollecito riaperto.")
    else:
        raise HTTPException(status_code=404)
    return redirect(ritorno)
