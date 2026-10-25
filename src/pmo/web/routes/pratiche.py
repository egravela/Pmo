"""Pratiche: elenco, dettaglio con cronologia, modifica, eventi, conferme e collegamenti manuali."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from pmo.config import get_settings
from pmo.db.models import (
    ETICHETTE_EVENTO,
    ETICHETTE_STATO,
    Cliente,
    Documento,
    Evento,
    Messaggio,
    Pratica,
    Prodotto,
    Sollecito,
    StatoMessaggio,
    StatoPratica,
    StatoSollecito,
    StatoVerifica,
    TipoEvento,
    TipoFonte,
    User,
)
from pmo.rules.engine import ordina_gravita
from pmo.services import pratiche as svc
from pmo.services.richieste import (
    AZIONI_DA_FARE,
    GIORNI_SCADENZA_VICINA,
    pratiche_con_azioni,
    richieste_in_attesa,
)
from pmo.web.deps import flash, get_db, pagina_per, redirect, render, utente_corrente, verifica_csrf

router = APIRouter()

PER_PAGINA_PRATICHE = 24

TIPI_EVENTO_MANUALI = [t.value for t in TipoEvento if t not in (TipoEvento.CAMBIO_STATO,)]


def _decimal(valore: str | None) -> Decimal | None:
    if valore is None or not valore.strip():
        return None
    pulito = valore.strip().replace("€", "").replace(" ", "")
    if "," in pulito and "." in pulito:
        pulito = pulito.replace(".", "").replace(",", ".")
    elif "," in pulito:
        pulito = pulito.replace(",", ".")
    try:
        return Decimal(pulito)
    except InvalidOperation as exc:
        raise HTTPException(status_code=400, detail=f"Importo non valido: {valore}") from exc


def _date(valore: str | None) -> date | None:
    if not valore:
        return None
    try:
        return date.fromisoformat(valore)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Data non valida: {valore}") from exc


def _riferimenti(testo: str | None) -> dict:
    out: dict[str, str] = {}
    for riga in (testo or "").splitlines():
        if "=" in riga:
            k, v = riga.split("=", 1)
            if k.strip() and v.strip():
                out[k.strip().lower().replace(" ", "_")] = v.strip()
    return out


def _carica(session: Session, pratica_id: int) -> Pratica:
    pratica = session.get(Pratica, pratica_id)
    if pratica is None:
        raise HTTPException(status_code=404, detail="Pratica non trovata")
    return pratica


@router.get("/pratiche")
def elenco(
    request: Request,
    q: str = "",
    stato: str = "",
    cliente_id: int | None = None,
    prodotto_id: int | None = None,
    responsabile_id: int | None = None,
    verifica: str = "",
    tutte: int = 0,
    azione: str = "",
    richieste: int = 0,  # vecchio nome del filtro "in attesa di una nostra risposta", tenuto per i link già in uso
    session: Session = Depends(get_db),
    utente: User = Depends(utente_corrente),
):
    query = select(Pratica)
    richieste_aperte = richieste_in_attesa(session)
    azioni = pratiche_con_azioni(session, richieste_aperte)
    azione = azione or ("risposta" if richieste else "")
    if azione in azioni:
        query = query.where(Pratica.id.in_(list(azioni[azione]) or [0]))
    else:
        azione = ""
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(Pratica.codice.ilike(like), Pratica.titolo.ilike(like), Pratica.descrizione.ilike(like)))
    if stato:
        query = query.where(Pratica.stato == stato)
    elif not tutte:
        query = query.where(Pratica.stato.notin_([StatoPratica.CHIUSA.value, StatoPratica.ANNULLATA.value]))
    if cliente_id:
        query = query.where(Pratica.cliente_id == cliente_id)
    if prodotto_id:
        query = query.where(Pratica.prodotto_id == prodotto_id)
    if responsabile_id:
        query = query.where(Pratica.responsabile_user_id == responsabile_id)
    if verifica == "proposte":
        query = query.where(Pratica.stato_verifica == StatoVerifica.PROPOSTO.value)
    else:
        query = query.where(Pratica.stato_verifica != StatoVerifica.RIFIUTATO.value)
    # Il riepilogo vale per tutto l'elenco filtrato, non per la sola pagina mostrata.
    filtrate = query.subquery()
    totale = session.scalar(select(func.count()).select_from(filtrate)) or 0
    riepilogo = {
        "totale": totale,
        "proposte": session.scalar(select(func.count()).select_from(filtrate).where(filtrate.c.stato_verifica == StatoVerifica.PROPOSTO.value)) or 0,
        "ordinato": session.scalar(select(func.sum(filtrate.c.importo_ordine))) or 0,
        "con_solleciti": session.scalar(
            select(func.count(func.distinct(Sollecito.pratica_id))).where(
                Sollecito.pratica_id.in_(select(filtrate.c.id)),
                Sollecito.stato.in_([StatoSollecito.APERTO.value, StatoSollecito.IN_CARICO.value]),
            )
        )
        or 0,
        "con_richieste": len(set(session.scalars(select(filtrate.c.id))) & set(richieste_aperte)),
        "con_azioni": len(set(session.scalars(select(filtrate.c.id))) & azioni["qualsiasi"]),
    }
    pagina = pagina_per(request, totale, PER_PAGINA_PRATICHE)
    pratiche = session.scalars(
        query.options(selectinload(Pratica.cliente), selectinload(Pratica.prodotto), selectinload(Pratica.responsabile), selectinload(Pratica.solleciti))
        .order_by(Pratica.ultimo_evento_at.desc().nullslast(), Pratica.id.desc())
        .offset(pagina.offset)
        .limit(pagina.per_pagina)
    ).all()
    clienti = session.scalars(select(Cliente).where(Cliente.attivo.is_(True)).order_by(Cliente.nome)).all()
    prodotti = session.scalars(select(Prodotto).where(Prodotto.attivo.is_(True)).order_by(Prodotto.nome)).all()
    utenti = session.scalars(select(User).where(User.attivo.is_(True)).order_by(User.nome)).all()
    return render(
        request,
        "pratiche/elenco.html",
        utente,
        pratiche=pratiche,
        pagina=pagina,
        riepilogo=riepilogo,
        clienti=clienti,
        prodotti=prodotti,
        utenti=utenti,
        richieste_aperte=richieste_aperte,
        azioni_da_fare=AZIONI_DA_FARE,
        scadenza_vicina=date.today() + timedelta(days=GIORNI_SCADENZA_VICINA),
        filtri={"q": q, "stato": stato, "cliente_id": cliente_id, "prodotto_id": prodotto_id, "responsabile_id": responsabile_id, "verifica": verifica, "tutte": tutte, "azione": azione},
        stati=ETICHETTE_STATO,
    )


@router.get("/pratiche/nuova")
def nuova(request: Request, session: Session = Depends(get_db), utente: User = Depends(utente_corrente)):
    clienti = session.scalars(select(Cliente).where(Cliente.attivo.is_(True)).order_by(Cliente.nome)).all()
    prodotti = session.scalars(select(Prodotto).where(Prodotto.attivo.is_(True)).order_by(Prodotto.nome)).all()
    utenti = session.scalars(select(User).where(User.attivo.is_(True)).order_by(User.nome)).all()
    return render(request, "pratiche/nuova.html", utente, clienti=clienti, prodotti=prodotti, utenti=utenti, stati=ETICHETTE_STATO)


@router.post("/pratiche", dependencies=[Depends(verifica_csrf)])
def crea(
    request: Request,
    titolo: str = Form(...),
    descrizione: str = Form(""),
    cliente_id: str = Form(""),
    prodotto_id: str = Form(""),
    stato: str = Form("bozza"),
    responsabile_id: str = Form(""),
    data_scadenza: str = Form(""),
    importo_offerta: str = Form(""),
    importo_ordine: str = Form(""),
    priorita: str = Form("media"),
    session: Session = Depends(get_db),
    utente: User = Depends(utente_corrente),
):
    pratica = svc.crea_pratica(
        session,
        titolo,
        descrizione=descrizione,
        cliente=session.get(Cliente, int(cliente_id)) if cliente_id else None,
        prodotto=session.get(Prodotto, int(prodotto_id)) if prodotto_id else None,
        stato=stato,
        responsabile_user_id=int(responsabile_id) if responsabile_id else utente.id,
        created_by_user_id=utente.id,
        data_scadenza=_date(data_scadenza),
        importo_offerta=_decimal(importo_offerta),
        importo_ordine=_decimal(importo_ordine),
        priorita=priorita,
    )
    flash(request, f"Pratica {pratica.codice} creata. Usa il tag {pratica.tag} nell'oggetto delle mail.")
    return redirect(f"/pratiche/{pratica.id}")


@router.get("/pratiche/{pratica_id}")
def dettaglio(request: Request, pratica_id: int, session: Session = Depends(get_db), utente: User = Depends(utente_corrente)):
    pratica = _carica(session, pratica_id)
    eventi = sorted(pratica.eventi, key=lambda e: (e.data_evento, e.id), reverse=True)
    messaggi = session.scalars(
        select(Messaggio).where(Messaggio.pratica_id == pratica.id).order_by(Messaggio.data.desc()).limit(200)
    ).all()
    documenti = session.scalars(
        select(Documento).where(Documento.pratica_id == pratica.id).order_by(Documento.modified_time.desc()).limit(200)
    ).all()
    solleciti = sorted(pratica.solleciti, key=lambda s: (s.stato != "aperto" and s.stato != "in_carico", ordina_gravita(s.gravita)))
    clienti = session.scalars(select(Cliente).where(Cliente.attivo.is_(True)).order_by(Cliente.nome)).all()
    prodotti = session.scalars(select(Prodotto).where(Prodotto.attivo.is_(True)).order_by(Prodotto.nome)).all()
    utenti = session.scalars(select(User).where(User.attivo.is_(True)).order_by(User.nome)).all()
    proposti = [e for e in eventi if e.stato_verifica == StatoVerifica.PROPOSTO]
    return render(
        request,
        "pratiche/dettaglio.html",
        utente,
        pratica=pratica,
        richieste_cliente=richieste_in_attesa(session, [pratica.id]).get(pratica.id, []),
        eventi=eventi,
        proposti=proposti,
        messaggi=messaggi,
        documenti=documenti,
        solleciti=solleciti,
        clienti=clienti,
        prodotti=prodotti,
        utenti=utenti,
        stati=ETICHETTE_STATO,
        tipi_evento=[(t, ETICHETTE_EVENTO[t]) for t in TIPI_EVENTO_MANUALI],
        riferimenti_testo="\n".join(f"{k}={v}" for k, v in (pratica.riferimenti or {}).items()),
    )


@router.post("/pratiche/{pratica_id}/modifica", dependencies=[Depends(verifica_csrf)])
def modifica(
    request: Request,
    pratica_id: int,
    titolo: str = Form(...),
    descrizione: str = Form(""),
    cliente_id: str = Form(""),
    prodotto_id: str = Form(""),
    responsabile_id: str = Form(""),
    priorita: str = Form("media"),
    data_scadenza: str = Form(""),
    importo_stima: str = Form(""),
    importo_offerta: str = Form(""),
    importo_ordine: str = Form(""),
    importo_fatturato: str = Form(""),
    riferimenti: str = Form(""),
    drive_folder_url: str = Form(""),
    note: str = Form(""),
    session: Session = Depends(get_db),
    utente: User = Depends(utente_corrente),
):
    pratica = _carica(session, pratica_id)
    pratica.titolo = titolo.strip()[:300]
    pratica.descrizione = descrizione
    pratica.cliente_id = int(cliente_id) if cliente_id else None
    pratica.prodotto_id = int(prodotto_id) if prodotto_id else None
    pratica.responsabile_user_id = int(responsabile_id) if responsabile_id else None
    pratica.priorita = priorita
    pratica.data_scadenza = _date(data_scadenza)
    pratica.importo_stima = _decimal(importo_stima)
    pratica.importo_offerta = _decimal(importo_offerta)
    pratica.importo_ordine = _decimal(importo_ordine)
    pratica.importo_fatturato = _decimal(importo_fatturato)
    pratica.riferimenti = _riferimenti(riferimenti)
    pratica.drive_folder_url = drive_folder_url.strip() or None
    pratica.note = note
    flash(request, "Pratica aggiornata.")
    return redirect(f"/pratiche/{pratica.id}")


@router.post("/pratiche/{pratica_id}/stato", dependencies=[Depends(verifica_csrf)])
def cambia_stato(request: Request, pratica_id: int, stato: str = Form(...), motivo: str = Form(""), session: Session = Depends(get_db), utente: User = Depends(utente_corrente)):
    pratica = _carica(session, pratica_id)
    try:
        svc.cambia_stato(session, pratica, stato, motivo=motivo, user_id=utente.id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Stato non valido") from None
    flash(request, f"Stato aggiornato a '{pratica.etichetta_stato}'.")
    return redirect(f"/pratiche/{pratica.id}")


@router.post("/pratiche/{pratica_id}/eventi", dependencies=[Depends(verifica_csrf)])
def aggiungi_evento(
    request: Request,
    pratica_id: int,
    tipo: str = Form(...),
    titolo: str = Form(...),
    descrizione: str = Form(""),
    data_evento: str = Form(""),
    importo: str = Form(""),
    scadenza: str = Form(""),
    session: Session = Depends(get_db),
    utente: User = Depends(utente_corrente),
):
    pratica = _carica(session, pratica_id)
    giorno = _date(data_evento)
    quando = datetime.combine(giorno, time(12, 0), tzinfo=UTC) if giorno else None
    svc.aggiungi_evento(
        session,
        pratica,
        tipo=tipo,
        titolo=titolo,
        descrizione=descrizione,
        data_evento=quando,
        fonte_tipo=TipoFonte.MANUALE,
        importo=_decimal(importo),
        scadenza=_date(scadenza),
        created_by_user_id=utente.id,
    )
    flash(request, "Evento registrato.")
    return redirect(f"/pratiche/{pratica.id}")


@router.post("/pratiche/{pratica_id}/eventi/{evento_id}/{azione}", dependencies=[Depends(verifica_csrf)])
def evento_azione(request: Request, pratica_id: int, evento_id: int, azione: str, session: Session = Depends(get_db), utente: User = Depends(utente_corrente)):
    evento = session.get(Evento, evento_id)
    if evento is None or evento.pratica_id != pratica_id:
        raise HTTPException(status_code=404)
    if azione == "conferma":
        svc.conferma_evento(session, evento, utente.id)
        flash(request, "Evento confermato.")
    elif azione == "rifiuta":
        svc.rifiuta_evento(session, evento, utente.id)
        flash(request, "Evento scartato.")
    elif azione == "elimina":
        session.delete(evento)
        flash(request, "Evento eliminato.")
    else:
        raise HTTPException(status_code=404)
    return redirect(f"/pratiche/{pratica_id}")


@router.post("/pratiche/{pratica_id}/conferma", dependencies=[Depends(verifica_csrf)])
def conferma(request: Request, pratica_id: int, session: Session = Depends(get_db), utente: User = Depends(utente_corrente)):
    pratica = _carica(session, pratica_id)
    svc.conferma_pratica(session, pratica, utente.id, soglia=get_settings().event_confidence_threshold)
    flash(request, f"Pratica {pratica.codice} confermata.")
    return redirect(f"/pratiche/{pratica.id}")


@router.post("/pratiche/{pratica_id}/scarta", dependencies=[Depends(verifica_csrf)])
def scarta(request: Request, pratica_id: int, session: Session = Depends(get_db), utente: User = Depends(utente_corrente)):
    pratica = _carica(session, pratica_id)
    svc.rifiuta_pratica(session, pratica, utente.id)
    flash(request, f"Pratica proposta {pratica.codice} scartata: i messaggi tornano in revisione.")
    return redirect("/revisione")


@router.post("/pratiche/{pratica_id}/unisci", dependencies=[Depends(verifica_csrf)])
def unisci(request: Request, pratica_id: int, codice: str = Form(...), session: Session = Depends(get_db), utente: User = Depends(utente_corrente)):
    pratica = _carica(session, pratica_id)
    destinazione = svc.trova_per_codice(session, codice.strip())
    if destinazione is None or destinazione.id == pratica.id:
        flash(request, "Codice pratica di destinazione non valido.", "errore")
        return redirect(f"/pratiche/{pratica.id}")
    svc.unisci_pratiche(session, pratica, destinazione, utente.id)
    flash(request, f"Pratica {pratica.codice} unita a {destinazione.codice}.")
    return redirect(f"/pratiche/{destinazione.id}")


# --- collegamenti manuali di messaggi e documenti -----------------------------------------------


def _collega_elemento(session: Session, elemento, codice: str, utente: User) -> Pratica | None:  # noqa: ANN001
    pratica = svc.trova_per_codice(session, codice.strip()) if codice.strip() else None
    if pratica is None:
        return None
    elemento.pratica_id = pratica.id
    elemento.link_origine = "manuale"
    elemento.stato = StatoMessaggio.CLASSIFICATO
    elemento.motivo = f"Collegato manualmente da {utente.email}"
    elemento.processed_at = datetime.now(UTC)
    for evento in session.scalars(select(Evento).where(Evento.messaggio_id == elemento.id if isinstance(elemento, Messaggio) else Evento.documento_id == elemento.id)).all():
        if evento.pratica_id != pratica.id:
            evento.pratica_id = pratica.id
        if evento.stato_verifica == StatoVerifica.PROPOSTO:
            svc.conferma_evento(session, evento, utente.id)
    return pratica


@router.post("/messaggi/{messaggio_id}/collega", dependencies=[Depends(verifica_csrf)])
def collega_messaggio(request: Request, messaggio_id: int, codice: str = Form(""), ritorno: str = Form("/revisione"), session: Session = Depends(get_db), utente: User = Depends(utente_corrente)):
    messaggio = session.get(Messaggio, messaggio_id)
    if messaggio is None:
        raise HTTPException(status_code=404)
    pratica = _collega_elemento(session, messaggio, codice, utente)
    if pratica is None:
        flash(request, "Codice pratica non trovato.", "errore")
    else:
        flash(request, f"Messaggio collegato a {pratica.codice}.")
    return redirect(ritorno)


@router.post("/messaggi/{messaggio_id}/{azione}", dependencies=[Depends(verifica_csrf)])
def messaggio_azione(request: Request, messaggio_id: int, azione: str, ritorno: str = Form("/revisione"), session: Session = Depends(get_db), utente: User = Depends(utente_corrente)):
    messaggio = session.get(Messaggio, messaggio_id)
    if messaggio is None:
        raise HTTPException(status_code=404)
    if azione == "conferma" and messaggio.pratica_id:
        _collega_elemento(session, messaggio, messaggio.pratica.codice, utente)
        flash(request, "Collegamento confermato.")
    elif azione == "ignora":
        messaggio.stato = StatoMessaggio.IGNORATO
        messaggio.motivo = f"Ignorato da {utente.email}"
        for evento in session.scalars(select(Evento).where(Evento.messaggio_id == messaggio.id, Evento.stato_verifica == StatoVerifica.PROPOSTO.value)).all():
            svc.rifiuta_evento(session, evento, utente.id)
        flash(request, "Messaggio ignorato.")
    elif azione == "scollega":
        messaggio.pratica_id = None
        messaggio.link_origine = None
        messaggio.stato = StatoMessaggio.DA_RIVEDERE
        flash(request, "Messaggio scollegato.")
    elif azione == "riclassifica":
        messaggio.stato = StatoMessaggio.NUOVO
        messaggio.classificazione = {}
        flash(request, "Il messaggio verrà riclassificato alla prossima sincronizzazione.")
    else:
        raise HTTPException(status_code=404)
    return redirect(ritorno)


@router.post("/documenti/{documento_id}/collega", dependencies=[Depends(verifica_csrf)])
def collega_documento(request: Request, documento_id: int, codice: str = Form(""), ritorno: str = Form("/revisione"), session: Session = Depends(get_db), utente: User = Depends(utente_corrente)):
    documento = session.get(Documento, documento_id)
    if documento is None:
        raise HTTPException(status_code=404)
    pratica = _collega_elemento(session, documento, codice, utente)
    if pratica is None:
        flash(request, "Codice pratica non trovato.", "errore")
    else:
        flash(request, f"Documento collegato a {pratica.codice}.")
    return redirect(ritorno)


@router.post("/documenti/{documento_id}/{azione}", dependencies=[Depends(verifica_csrf)])
def documento_azione(request: Request, documento_id: int, azione: str, ritorno: str = Form("/revisione"), session: Session = Depends(get_db), utente: User = Depends(utente_corrente)):
    documento = session.get(Documento, documento_id)
    if documento is None:
        raise HTTPException(status_code=404)
    if azione == "conferma" and documento.pratica_id:
        _collega_elemento(session, documento, documento.pratica.codice, utente)
        flash(request, "Collegamento confermato.")
    elif azione == "ignora":
        documento.stato = StatoMessaggio.IGNORATO
        documento.motivo = f"Ignorato da {utente.email}"
        flash(request, "Documento ignorato.")
    elif azione == "riclassifica":
        documento.stato = StatoMessaggio.NUOVO
        documento.classificazione = {}
        flash(request, "Il documento verrà riclassificato alla prossima sincronizzazione.")
    else:
        raise HTTPException(status_code=404)
    return redirect(ritorno)
