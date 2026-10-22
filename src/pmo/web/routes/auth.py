"""Login con Google (OpenID) o, in sviluppo, con la sola email."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pmo.config import get_settings
from pmo.connectors.google_oauth import GoogleNonConfigurato, completa_login, dominio_consentito, url_login
from pmo.db.base import utcnow
from pmo.db.models import User
from pmo.web.deps import flash, get_db, redirect, render, verifica_csrf

log = logging.getLogger(__name__)
router = APIRouter()


def _destinazione_sicura(next_url: str | None) -> str:
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return "/"


def _accedi(request: Request, session: Session, email: str, nome: str = "", google_sub: str | None = None) -> User | None:
    settings = get_settings()
    email = email.lower().strip()
    if not dominio_consentito(email, settings):
        return None
    utente = session.scalar(select(User).where(User.email == email))
    primo = (session.scalar(select(func.count()).select_from(User)) or 0) == 0
    if utente is None:
        if not (primo or email in settings.admin_emails or settings.allowed_domains):
            return None
        utente = User(email=email, nome=nome or email, ruolo="membro", attivo=True, riceve_digest=True)
        session.add(utente)
        session.flush()
    if not utente.attivo:
        return None
    if primo or email in settings.admin_emails:
        utente.ruolo = "admin"
    if nome and not utente.nome:
        utente.nome = nome
    if google_sub:
        utente.google_sub = google_sub
    utente.last_login_at = utcnow()
    session.flush()
    request.session["user_id"] = utente.id
    return utente


@router.get("/login")
def login(request: Request, next: str | None = None):  # noqa: A002
    settings = get_settings()
    if request.session.get("user_id"):
        return redirect(_destinazione_sicura(next))
    return render(request, "login.html", google=settings.google_configured, dev_login=settings.dev_login, next=next or "/")


@router.get("/auth/google")
def auth_google(request: Request, next: str | None = None):  # noqa: A002
    try:
        url, state = url_login()
    except GoogleNonConfigurato as exc:
        flash(request, str(exc), "errore")
        return redirect("/login")
    request.session["oauth_state"] = state
    request.session["oauth_next"] = _destinazione_sicura(next)
    return redirect(url)


@router.get("/auth/callback")
def auth_callback(request: Request, session: Session = Depends(get_db)):
    state = request.session.pop("oauth_state", None)
    destinazione = request.session.pop("oauth_next", "/")
    if not state or request.query_params.get("state") != state:
        flash(request, "Sessione di login non valida: riprovare.", "errore")
        return redirect("/login")
    try:
        claims = completa_login(str(request.url), state)
    except Exception as exc:  # noqa: BLE001
        log.exception("Login Google fallito")
        flash(request, f"Login Google fallito: {exc}", "errore")
        return redirect("/login")
    utente = _accedi(request, session, claims["email"], claims.get("nome", ""), claims.get("sub"))
    if utente is None:
        flash(request, f"L'indirizzo {claims['email']} non è abilitato ad accedere.", "errore")
        return redirect("/login")
    return redirect(destinazione)


@router.post("/auth/dev", dependencies=[Depends(verifica_csrf)])
def auth_dev(request: Request, email: str = Form(...), next: str = Form("/"), session: Session = Depends(get_db)):  # noqa: A002
    settings = get_settings()
    if not settings.dev_login:
        flash(request, "Login di sviluppo disabilitato.", "errore")
        return redirect("/login")
    utente = _accedi(request, session, email, email.split("@")[0])
    if utente is None:
        flash(request, "Indirizzo non abilitato.", "errore")
        return redirect("/login")
    return redirect(_destinazione_sicura(next))


@router.post("/logout", dependencies=[Depends(verifica_csrf)])
def logout(request: Request):
    request.session.clear()
    return redirect("/login")
