"""Dipendenze comuni delle route: sessione DB, utente corrente, CSRF, rendering e messaggi flash."""

from __future__ import annotations

import math
import secrets
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pmo.config import get_settings
from pmo.db.models import ETICHETTE_EVENTO, ETICHETTE_STATO, FASI_ORDINATE, User
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


@dataclass
class Pagina:
    """Una pagina di un elenco: numero corrente, misura, totale e collegamenti alle altre pagine."""

    numero: int
    per_pagina: int
    totale: int
    percorso: str = "/"
    parametri: list[tuple[str, str]] = field(default_factory=list)

    @property
    def pagine(self) -> int:
        return max(1, math.ceil(self.totale / self.per_pagina))

    @property
    def offset(self) -> int:
        return (self.numero - 1) * self.per_pagina

    @property
    def inizio(self) -> int:
        return 0 if self.totale == 0 else self.offset + 1

    @property
    def fine(self) -> int:
        return min(self.totale, self.offset + self.per_pagina)

    def url(self, numero: int) -> str:
        coppie = [(k, v) for k, v in self.parametri if k != "pagina"]
        if numero > 1:
            coppie.append(("pagina", str(numero)))
        return self.percorso + ("?" + urlencode(coppie) if coppie else "")

    @property
    def finestra(self) -> list[int | None]:
        """Numeri da mostrare: la prima, l'ultima e due attorno alla corrente; None dove si salta."""
        vicine = {1, self.pagine, *range(self.numero - 2, self.numero + 3)}
        numeri = sorted(n for n in vicine if 1 <= n <= self.pagine)
        out: list[int | None] = []
        for n in numeri:
            if out and n - (out[-1] or 0) > 1:
                out.append(None)
            out.append(n)
        return out


def pagina_per(request: Request, totale: int, per_pagina: int) -> Pagina:
    """Legge ?pagina= e lo riporta dentro i limiti: una pagina oltre l'ultima mostra l'ultima."""
    try:
        numero = int(request.query_params.get("pagina", "1"))
    except ValueError:
        numero = 1
    pagine = max(1, math.ceil(totale / per_pagina))
    return Pagina(
        numero=min(max(numero, 1), pagine),
        per_pagina=per_pagina,
        totale=totale,
        percorso=request.url.path,
        parametri=list(request.query_params.multi_items()),
    )


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


def f_migliaia(valore: Decimal | float | None) -> str:
    """Importo in migliaia di euro per la cifra in evidenza: 46500 -> "46,5", 1250000 -> "1.250"."""
    if valore is None:
        return "-"
    k = Decimal(valore) / 1000
    if k >= 100:
        return f"{k:,.0f}".replace(",", ".")
    return f"{k:.1f}".replace(".", ",")


def f_contatori(valore: dict | None, prefisso: str = "") -> str:
    """I contatori di un'esecuzione in frase: {"da_rivedere": 542, "token": {"chiamate": 515}} -> "da rivedere 542 · token chiamate 515"."""
    voci = []
    for chiave, v in (valore or {}).items():
        etichetta = f"{prefisso}{chiave}".replace("_", " ")
        if isinstance(v, dict):
            voci.append(f_contatori(v, f"{etichetta} "))
        elif isinstance(v, bool):
            voci.append(f"{etichetta} {'sì' if v else 'no'}")
        elif isinstance(v, int):
            voci.append(f"{etichetta} {v:,}".replace(",", "."))
        else:
            voci.append(f"{etichetta} {v}")
    return " · ".join(x for x in voci if x)


ETICHETTE_ESECUZIONE = {
    "gmail": "Lettura di Gmail",
    "drive": "Lettura di Drive",
    "classify": "Classificazione mail",
    "classify_drive": "Classificazione documenti",
    "regole": "Calcolo dei solleciti",
    "digest": "Digest",
}


def f_esecuzione(valore: str) -> str:
    return ETICHETTE_ESECUZIONE.get(valore, valore)


def f_stato(valore: str) -> str:
    return ETICHETTE_STATO.get(valore, valore)


def f_evento(valore: str) -> str:
    return ETICHETTE_EVENTO.get(valore, valore)


def f_giorni_fa(valore: datetime | date | None) -> str:
    if valore is None:
        return "-"
    # Giorni di calendario nel fuso dell'app, gli stessi della data mostrata accanto: una mail di ieri sera
    # è "ieri" anche se sono passate meno di 24 ore.
    oggi = datetime.now(_tz()).date()
    if isinstance(valore, datetime):
        if valore.tzinfo is None:
            valore = valore.replace(tzinfo=UTC)
        giorni = (oggi - valore.astimezone(_tz()).date()).days
    else:
        giorni = (oggi - valore).days
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
    {"data": f_data, "datadt": f_datadt, "ora": f_ora, "euro": f_euro, "migliaia": f_migliaia, "contatori": f_contatori, "esecuzione": f_esecuzione, "stato": f_stato, "evento": f_evento, "giorni_fa": f_giorni_fa}
)
templates.env.globals["asset_v"] = _versione_statici()
templates.env.globals["ETICHETTE_STATO"] = ETICHETTE_STATO
templates.env.globals["FASI"] = [str(f.value) for f in FASI_ORDINATE]
templates.env.globals["ETICHETTE_EVENTO"] = ETICHETTE_EVENTO


def _conteggi_menu() -> dict[str, int]:
    """I numeri accanto alle voci del menu: cio' che aspetta qualcuno. Se il database non risponde, niente numeri."""
    from pmo.db.models import (
        Documento,
        Messaggio,
        Pratica,
        Sollecito,
        StatoMessaggio,
        StatoSollecito,
        StatoVerifica,
    )

    try:
        with get_session() as s:
            return {
                "solleciti": s.scalar(select(func.count(Sollecito.id)).where(Sollecito.stato.in_([StatoSollecito.APERTO.value, StatoSollecito.IN_CARICO.value]))) or 0,
                "revisione": (s.scalar(select(func.count(Pratica.id)).where(Pratica.stato_verifica == StatoVerifica.PROPOSTO.value)) or 0)
                + (s.scalar(select(func.count(Messaggio.id)).where(Messaggio.stato == StatoMessaggio.DA_RIVEDERE.value)) or 0)
                + (s.scalar(select(func.count(Documento.id)).where(Documento.stato == StatoMessaggio.DA_RIVEDERE.value)) or 0),
            }
    except Exception:  # noqa: BLE001
        return {}


def render(request: Request, nome: str, utente: User | None = None, **contesto: Any) -> HTMLResponse:
    settings = get_settings()
    messaggi = request.session.pop("flash", []) if "session" in request.scope else []
    if utente is not None and "conteggi_menu" not in contesto:
        contesto["conteggi_menu"] = _conteggi_menu()
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
