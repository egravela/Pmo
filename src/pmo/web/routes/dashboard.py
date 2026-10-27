"""Cruscotto: situazione complessiva delle pratiche, solleciti, revisione e caselle."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from pmo.db.models import (
    FASI_ORDINATE,
    Account,
    Documento,
    Evento,
    Messaggio,
    Pratica,
    Sollecito,
    StatoMessaggio,
    StatoPratica,
    StatoSollecito,
    StatoVerifica,
    SyncRun,
    TipoFonte,
    User,
)
from pmo.rules.engine import ordina_gravita
from pmo.services.richieste import attese_cliente, richieste_in_attesa
from pmo.web.deps import get_db, render, utente_corrente

router = APIRouter()


@router.get("/")
def dashboard(request: Request, session: Session = Depends(get_db), utente: User = Depends(utente_corrente)):
    per_stato_raw = dict(
        session.execute(
            select(Pratica.stato, func.count()).where(Pratica.stato_verifica == StatoVerifica.CONFERMATO.value).group_by(Pratica.stato)
        ).all()
    )
    per_stato = [(s.value, per_stato_raw.get(s.value, 0)) for s in FASI_ORDINATE if s != StatoPratica.CHIUSA]
    totale_attive = sum(n for _, n in per_stato)

    solleciti = session.scalars(
        select(Sollecito)
        .options(selectinload(Sollecito.pratica).selectinload(Pratica.cliente))
        .where(Sollecito.stato.in_([StatoSollecito.APERTO.value, StatoSollecito.IN_CARICO.value]))
    ).all()
    oggi = date.today()
    solleciti = [s for s in solleciti if not (s.snooze_fino and s.snooze_fino > oggi)]
    solleciti.sort(key=lambda s: (ordina_gravita(s.gravita), s.aperto_il), reverse=False)
    per_gravita = {"critico": 0, "avviso": 0, "info": 0}
    for s in solleciti:
        per_gravita[s.gravita] = per_gravita.get(s.gravita, 0) + 1

    da_rivedere = {
        "messaggi": session.scalar(select(func.count()).select_from(Messaggio).where(Messaggio.stato == StatoMessaggio.DA_RIVEDERE.value)) or 0,
        "documenti": session.scalar(select(func.count()).select_from(Documento).where(Documento.stato == StatoMessaggio.DA_RIVEDERE.value)) or 0,
        "pratiche": session.scalar(select(func.count()).select_from(Pratica).where(Pratica.stato_verifica == StatoVerifica.PROPOSTO.value)) or 0,
        "errori": session.scalar(select(func.count()).select_from(Messaggio).where(Messaggio.stato == StatoMessaggio.ERRORE.value)) or 0,
    }
    in_attesa_ia = session.scalar(select(func.count()).select_from(Messaggio).where(Messaggio.stato == StatoMessaggio.NUOVO.value)) or 0

    scadenze = session.scalars(
        select(Pratica)
        .options(selectinload(Pratica.cliente))
        .where(
            Pratica.data_scadenza.isnot(None),
            Pratica.data_scadenza <= oggi + timedelta(days=14),
            Pratica.stato.notin_([StatoPratica.CHIUSA.value, StatoPratica.ANNULLATA.value]),
        )
        .order_by(Pratica.data_scadenza)
        .limit(10)
    ).all()

    eventi = session.scalars(
        select(Evento)
        .options(selectinload(Evento.pratica))
        .where(Evento.fonte_tipo != TipoFonte.SISTEMA.value)
        .order_by(Evento.created_at.desc())
        .limit(15)
    ).all()

    caselle = session.scalars(select(Account).options(selectinload(Account.watched_folders)).order_by(Account.email)).all()
    ultime_run = session.scalars(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(5)).all()

    # Richieste dei clienti verso di noi ancora senza risposta: le più vecchie per prime, perché sono le più in ritardo.
    aperte = richieste_in_attesa(session)
    pratiche_con_richieste = {
        p.id: p
        for p in session.scalars(select(Pratica).options(selectinload(Pratica.cliente)).where(Pratica.id.in_(list(aperte) or [0])))
    }
    richieste_cliente = sorted(
        ((r[0], pratiche_con_richieste[pid]) for pid, r in aperte.items() if pid in pratiche_con_richieste),
        key=lambda coppia: coppia[0].data,
    )
    # ... e quelle che aspettiamo noi dal cliente, sempre dalla più vecchia.
    attese = attese_cliente(session)
    pratiche_in_attesa = {
        p.id: p
        for p in session.scalars(select(Pratica).options(selectinload(Pratica.cliente)).where(Pratica.id.in_(list(attese) or [0])))
    }
    attese_del_cliente = sorted(
        ((a[0], pratiche_in_attesa[pid]) for pid, a in attese.items() if pid in pratiche_in_attesa),
        key=lambda coppia: coppia[0].data,
    )

    return render(
        request,
        "dashboard.html",
        utente,
        per_stato=per_stato,
        totale_attive=totale_attive,
        solleciti=solleciti[:12],
        totale_solleciti=len(solleciti),
        per_gravita=per_gravita,
        da_rivedere=da_rivedere,
        in_attesa_ia=in_attesa_ia,
        scadenze=scadenze,
        eventi=eventi,
        caselle=caselle,
        ultime_run=ultime_run,
        richieste_cliente=richieste_cliente[:10],
        totale_richieste_cliente=len(richieste_cliente),
        attese_del_cliente=attese_del_cliente[:10],
        totale_attese_del_cliente=len(attese_del_cliente),
    )
