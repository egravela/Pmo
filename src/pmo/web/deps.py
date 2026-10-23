"""Dipendenze comuni delle route: sessione DB, utente corrente, CSRF, rendering e messaggi flash."""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from pmo.config import get_settings
from pmo.db.models import ETICHETTE_EVENTO, ETICHETTE_STATO, User
from pmo.db.session import get_session

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"


class NonAutenticato(Exception):
    pass


def get_db() -> Iterator[Session]:
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def utente_corrente(request: Request, session: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise NonAutenticato()
    utente = session.get(User, user_id)
    if utente is None or not utente.attivo:
        request.session.clear()
        raise NonAutenticato()
    return utente


def admin_richiesto(utente: User = Depends(utente_corrente)) -> User:
    if not utente.is_admin:
        raise HTTPException(status_code=403, detail="Operazione riservata agli amministratori")
    return utente


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


async def verifica_csrf(request: Request) -> None:
    form = await request.form()
    atteso = request.session.get("csrf")
    ricevuto = form.get("csrf_token")
    if not atteso or not ricevuto or not secrets.compare_digest(str(atteso), str(ricevuto)):
        raise HTTPException(status_code=400, detail="Token CSRF non valido: ricaricare la pagina e riprovare")


def flash(request: Request, messaggio: str, livello: str = "ok") -> None:
    lista = list(request.session.get("flash") or [])
    lista.append([livello, messaggio])
    request.session["flash"] = lista[-5:]


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


# --- filtri Jinja --------------------------------------------------------------------------


def _tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def f_data(valore: date | datetime | None) -> str:
    if valore is None:
        return "-"
    if isinstance(valore, datetime):
        if valore.tzinfo is None:
            valore = valore.replace(tzinfo=UTC)
        valore = valore.astimezone(_tz())
    return valore.strftime("%d/%m/%Y")


def f_datadt(valore: datetime | None) -> str:
    if valore is None:
        return "-"
    if valore.tzinfo is None:
        valore = valore.replace(tzinfo=UTC)
    return valore.astimezone(_tz()).strftime("%d/%m/%Y %H:%M")


def f_ora(valore: datetime | None) -> str:
    if valore is None:
        return "-"
    if valore.tzinfo is None:
        valore = valore.replace(tzinfo=UTC)
    return valore.astimezone(_tz()).strftime("%H:%M")


def f_euro(valore: Decimal | float | None) -> str:
    if valore is None:
        return "-"
    testo = f"{Decimal(valore):,.2f}"
    return testo.replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def f_stato(valore: str) -> str:
    return ETICHETTE_STATO.get(valore, valore)


def f_evento(valore: str) -> str:
    return ETICHETTE_EVENTO.get(valore, valore)


def f_giorni_fa(valore: datetime | date | None) -> str:
    if valore is None:
        return "-"
    if isinstance(valore, datetime):
        if valore.tzinfo is None:
            valore = valore.replace(tzinfo=UTC)
        giorni = (datetime.now(UTC) - valore).days
    else:
        giorni = (date.today() - valore).days
    if giorni <= 0:
        return "oggi"
    if giorni == 1:
        return "ieri"
    return f"{giorni} giorni fa"


def _versione_statici() -> str:
    """Cambia quando cambia un file statico: evita che il browser serva il CSS vecchio dopo un aggiornamento."""
    tempi = [p.stat().st_mtime_ns for p in STATIC_DIR.rglob("*") if p.is_file()]
    return str(max(tempi) // 1_000_000_000) if tempi else "0"


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters.update(
    {"data": f_data, "datadt": f_datadt, "ora": f_ora, "euro": f_euro, "stato": f_stato, "evento": f_evento, "giorni_fa": f_giorni_fa}
)
templates.env.globals["asset_v"] = _versione_statici()
templates.env.globals["ETICHETTE_STATO"] = ETICHETTE_STATO
templates.env.globals["ETICHETTE_EVENTO"] = ETICHETTE_EVENTO


def render(request: Request, nome: str, utente: User | None = None, **contesto: Any) -> HTMLResponse:
    settings = get_settings()
    messaggi = request.session.pop("flash", []) if "session" in request.scope else []
    contesto.update(
        {
            "request": request,
            "utente": utente,
            "csrf_token": csrf_token(request),
            "flash_messaggi": messaggi,
            "app_name": settings.app_name,
            "settings": settings,
            "oggi": date.today(),
        }
    )
    return templates.TemplateResponse(request, nome, contesto)
