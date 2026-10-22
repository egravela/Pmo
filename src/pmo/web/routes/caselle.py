"""Caselle collegate: collegamento OAuth, cartelle Drive monitorate, sincronizzazione manuale."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from pmo.config import get_settings
from pmo.connectors.drive import DriveClient, estrai_folder_id
from pmo.connectors.gmail import GmailClient
from pmo.connectors.google_oauth import (
    GoogleNonConfigurato,
    completa_collegamento,
    credentials_per_account,
    salva_token,
    url_collega_casella,
)
from pmo.db.models import Account, SyncRun, User, WatchedFolder
from pmo.services.sync import account_in_sincronizzazione, esegui_regole_tutto, sincronizza_account
from pmo.web.deps import admin_richiesto, flash, get_db, redirect, render, utente_corrente, verifica_csrf

log = logging.getLogger(__name__)
router = APIRouter()


def _carica(session: Session, account_id: int, utente: User) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Casella non trovata")
    if not utente.is_admin and account.owner_user_id != utente.id:
        raise HTTPException(status_code=403, detail="Casella di un altro utente")
    return account


@router.get("/caselle")
def elenco(request: Request, session: Session = Depends(get_db), utente: User = Depends(utente_corrente)):
    settings = get_settings()
    accounts = session.scalars(select(Account).options(selectinload(Account.watched_folders), selectinload(Account.owner)).order_by(Account.email)).all()
    if not utente.is_admin:
        accounts = [a for a in accounts if a.owner_user_id == utente.id]
    run_per_account: dict[int, list[SyncRun]] = {}
    for run in session.scalars(select(SyncRun).where(SyncRun.account_id.isnot(None)).order_by(SyncRun.started_at.desc()).limit(60)).all():
        lista = run_per_account.setdefault(run.account_id, [])
        if len(lista) < 4:
            lista.append(run)
    return render(
        request,
        "caselle/elenco.html",
        utente,
        accounts=accounts,
        run_per_account=run_per_account,
        google=settings.google_configured,
        in_sync={a.id: account_in_sincronizzazione(a.id) for a in accounts},
    )


@router.post("/caselle/collega", dependencies=[Depends(verifica_csrf)])
def collega(request: Request, login_hint: str = Form(""), utente: User = Depends(utente_corrente)):
    try:
        url, state = url_collega_casella(login_hint=login_hint or utente.email)
    except GoogleNonConfigurato as exc:
        flash(request, str(exc), "errore")
        return redirect("/caselle")
    request.session["oauth_state_account"] = state
    return redirect(url)


@router.get("/caselle/callback")
def callback(request: Request, session: Session = Depends(get_db), utente: User = Depends(utente_corrente)):
    state = request.session.pop("oauth_state_account", None)
    if not state or request.query_params.get("state") != state:
        flash(request, "Sessione OAuth non valida: riprovare.", "errore")
        return redirect("/caselle")
    try:
        claims, token = completa_collegamento(str(request.url), state)
    except Exception as exc:  # noqa: BLE001
        log.exception("Collegamento casella fallito")
        flash(request, f"Collegamento fallito: {exc}", "errore")
        return redirect("/caselle")
    email = claims["email"]
    account = session.scalar(select(Account).where(Account.email == email))
    if account is None:
        account = Account(email=email, display_name=claims.get("nome") or email, owner_user_id=utente.id)
        session.add(account)
    elif account.owner_user_id is None:
        account.owner_user_id = utente.id
    salva_token(account, token)
    account.attivo = True
    account.last_error = None
    try:
        profilo = GmailClient(credentials_per_account(account)).profile()
        if not account.gmail_history_id:
            account.gmail_history_id = None  # la prima sincronizzazione usa la finestra temporale
        account.display_name = account.display_name or profilo.get("emailAddress", email)
    except Exception as exc:  # noqa: BLE001
        log.warning("Profilo Gmail non leggibile per %s: %s", email, exc)
    session.flush()
    flash(request, f"Casella {email} collegata. Aggiungi le cartelle Drive da monitorare e avvia la prima sincronizzazione.")
    return redirect("/caselle")


@router.post("/caselle/{account_id}/modifica", dependencies=[Depends(verifica_csrf)])
def modifica(
    request: Request,
    account_id: int,
    query_filter: str = Form(""),
    sync_gmail: str = Form(""),
    sync_drive: str = Form(""),
    attivo: str = Form(""),
    session: Session = Depends(get_db),
    utente: User = Depends(utente_corrente),
):
    account = _carica(session, account_id, utente)
    account.query_filter = query_filter.strip()[:500]
    account.sync_gmail = bool(sync_gmail)
    account.sync_drive = bool(sync_drive)
    account.attivo = bool(attivo)
    flash(request, "Impostazioni della casella aggiornate.")
    return redirect("/caselle")


@router.post("/caselle/{account_id}/cartelle", dependencies=[Depends(verifica_csrf)])
def aggiungi_cartella(request: Request, account_id: int, cartella: str = Form(...), ricorsivo: str = Form("1"), session: Session = Depends(get_db), utente: User = Depends(utente_corrente)):
    account = _carica(session, account_id, utente)
    folder_id = estrai_folder_id(cartella)
    if not folder_id:
        flash(request, "Indicare l'ID o l'URL della cartella.", "errore")
        return redirect("/caselle")
    try:
        meta = DriveClient(credentials_per_account(account)).get_file(folder_id)
    except Exception as exc:  # noqa: BLE001
        flash(request, f"Cartella non accessibile: {exc}", "errore")
        return redirect("/caselle")
    esistente = session.scalar(select(WatchedFolder).where(WatchedFolder.account_id == account.id, WatchedFolder.drive_folder_id == folder_id))
    if esistente is not None:
        esistente.attivo = True
        esistente.nome = meta.get("name", esistente.nome)
    else:
        session.add(WatchedFolder(account_id=account.id, drive_folder_id=folder_id, nome=meta.get("name", ""), ricorsivo=bool(ricorsivo)))
    flash(request, f"Cartella '{meta.get('name')}' monitorata.")
    return redirect("/caselle")


@router.post("/caselle/{account_id}/cartelle/{folder_id}/elimina", dependencies=[Depends(verifica_csrf)])
def elimina_cartella(request: Request, account_id: int, folder_id: int, session: Session = Depends(get_db), utente: User = Depends(utente_corrente)):
    account = _carica(session, account_id, utente)
    folder = session.get(WatchedFolder, folder_id)
    if folder is None or folder.account_id != account.id:
        raise HTTPException(status_code=404)
    session.delete(folder)
    flash(request, "Cartella rimossa dal monitoraggio (i documenti già importati restano).")
    return redirect("/caselle")


def _sync_in_background(account_id: int, completa: bool, giorni: int | None) -> None:
    try:
        esito = sincronizza_account(account_id, completa=completa, giorni=giorni)
        esegui_regole_tutto()
        log.info("Sincronizzazione manuale account %s: %s", account_id, esito)
    except Exception:  # noqa: BLE001
        log.exception("Sincronizzazione manuale fallita per account %s", account_id)


@router.post("/caselle/{account_id}/sync", dependencies=[Depends(verifica_csrf)])
def sync(
    request: Request,
    account_id: int,
    background: BackgroundTasks,
    completa: str = Form(""),
    giorni: str = Form(""),
    session: Session = Depends(get_db),
    utente: User = Depends(utente_corrente),
):
    account = _carica(session, account_id, utente)
    if not account.collegato:
        flash(request, "La casella non è collegata.", "errore")
        return redirect("/caselle")
    if account_in_sincronizzazione(account.id):
        flash(request, "Sincronizzazione già in corso.", "avviso")
        return redirect("/caselle")
    background.add_task(_sync_in_background, account.id, bool(completa), int(giorni) if giorni.strip().isdigit() else None)
    flash(request, f"Sincronizzazione di {account.email} avviata in background: ricarica la pagina tra qualche minuto.")
    return redirect("/caselle")


@router.post("/caselle/{account_id}/scollega", dependencies=[Depends(verifica_csrf)])
def scollega(request: Request, account_id: int, session: Session = Depends(get_db), utente: User = Depends(utente_corrente)):
    account = _carica(session, account_id, utente)
    account.token_cifrato = None
    account.scopes = []
    account.attivo = False
    flash(request, f"Casella {account.email} scollegata: i token sono stati eliminati.")
    return redirect("/caselle")


@router.get("/caselle/{account_id}/esecuzioni")
def esecuzioni(request: Request, account_id: int, session: Session = Depends(get_db), utente: User = Depends(utente_corrente)):
    account = _carica(session, account_id, utente)
    runs = session.scalars(select(SyncRun).where(SyncRun.account_id == account.id).order_by(SyncRun.started_at.desc()).limit(100)).all()
    return render(request, "caselle/esecuzioni.html", utente, account=account, runs=runs)


@router.post("/caselle/{account_id}/elimina", dependencies=[Depends(verifica_csrf)])
def elimina(request: Request, account_id: int, session: Session = Depends(get_db), utente: User = Depends(admin_richiesto)):
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404)
    session.delete(account)
    flash(request, f"Casella {account.email} eliminata con i suoi messaggi e documenti importati.")
    return redirect("/caselle")
