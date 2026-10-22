"""Impostazioni: regole, filtri anti-rumore, digest, clienti, prodotti, utenti."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from pmo.db.models import Cliente, Prodotto, Regola, User
from pmo.rules.definitions import assicura_regole
from pmo.services.impostazioni import get_impostazione, set_impostazione
from pmo.web.deps import admin_richiesto, flash, get_db, redirect, render, verifica_csrf

router = APIRouter()


def _righe(testo: str) -> list[str]:
    return [r.strip() for r in (testo or "").splitlines() if r.strip()]


@router.get("/impostazioni")
def pagina(request: Request, scheda: str = "regole", session: Session = Depends(get_db), utente: User = Depends(admin_richiesto)):
    regole = sorted(assicura_regole(session).values(), key=lambda r: r.nome)
    filtri = get_impostazione(session, "filtri")
    digest = get_impostazione(session, "digest")
    clienti = session.scalars(select(Cliente).order_by(Cliente.nome)).all()
    prodotti = session.scalars(select(Prodotto).order_by(Prodotto.nome)).all()
    utenti = session.scalars(select(User).order_by(User.email)).all()
    return render(
        request,
        "impostazioni.html",
        utente,
        scheda=scheda,
        regole=regole,
        filtri=filtri,
        digest=digest,
        clienti=clienti,
        prodotti=prodotti,
        utenti=utenti,
    )


@router.post("/impostazioni/regole/{regola_id}", dependencies=[Depends(verifica_csrf)])
def regola(request: Request, regola_id: int, soglia_giorni: str = Form(""), gravita: str = Form("avviso"), attiva: str = Form(""), session: Session = Depends(get_db), utente: User = Depends(admin_richiesto)):
    r = session.get(Regola, regola_id)
    if r is None:
        raise HTTPException(status_code=404)
    r.soglia_giorni = int(soglia_giorni) if soglia_giorni.strip().isdigit() else r.soglia_giorni
    r.gravita = gravita
    r.attiva = bool(attiva)
    flash(request, f"Regola '{r.nome}' aggiornata.")
    return redirect("/impostazioni?scheda=regole")


@router.post("/impostazioni/filtri", dependencies=[Depends(verifica_csrf)])
def filtri(
    request: Request,
    ignore_senders: str = Form(""),
    ignore_domains: str = Form(""),
    keep_senders: str = Form(""),
    ignore_sender_patterns: str = Form(""),
    ignore_subject_patterns: str = Form(""),
    session: Session = Depends(get_db),
    utente: User = Depends(admin_richiesto),
):
    set_impostazione(
        session,
        "filtri",
        {
            "ignore_senders": [s.lower() for s in _righe(ignore_senders)],
            "ignore_domains": [s.lower() for s in _righe(ignore_domains)],
            "keep_senders": [s.lower() for s in _righe(keep_senders)],
            "ignore_sender_patterns": _righe(ignore_sender_patterns),
            "ignore_subject_patterns": _righe(ignore_subject_patterns),
        },
    )
    flash(request, "Filtri aggiornati: valgono per i messaggi importati da ora in poi.")
    return redirect("/impostazioni?scheda=filtri")


@router.post("/impostazioni/digest", dependencies=[Depends(verifica_csrf)])
def digest(request: Request, destinatari: str = Form(""), attivo: str = Form(""), session: Session = Depends(get_db), utente: User = Depends(admin_richiesto)):
    set_impostazione(session, "digest", {"attivo": bool(attivo), "destinatari": [d.lower() for d in _righe(destinatari)]})
    flash(request, "Impostazioni del digest aggiornate.")
    return redirect("/impostazioni?scheda=digest")


@router.post("/impostazioni/clienti", dependencies=[Depends(verifica_csrf)])
def cliente(
    request: Request,
    cliente_id: str = Form(""),
    nome: str = Form(...),
    alias: str = Form(""),
    domini: str = Form(""),
    tipo: str = Form("altro"),
    attivo: str = Form("1"),
    session: Session = Depends(get_db),
    utente: User = Depends(admin_richiesto),
):
    c = session.get(Cliente, int(cliente_id)) if cliente_id else None
    if c is None:
        c = Cliente(nome=nome.strip())
        session.add(c)
    c.nome = nome.strip()
    c.alias = [a.strip() for a in alias.split(",") if a.strip()]
    c.domini = [d.strip().lower() for d in domini.split(",") if d.strip()]
    c.tipo = tipo
    c.attivo = bool(attivo)
    flash(request, f"Cliente '{c.nome}' salvato.")
    return redirect("/impostazioni?scheda=clienti")


@router.post("/impostazioni/prodotti", dependencies=[Depends(verifica_csrf)])
def prodotto(request: Request, prodotto_id: str = Form(""), nome: str = Form(...), alias: str = Form(""), descrizione: str = Form(""), attivo: str = Form("1"), session: Session = Depends(get_db), utente: User = Depends(admin_richiesto)):
    p = session.get(Prodotto, int(prodotto_id)) if prodotto_id else None
    if p is None:
        p = Prodotto(nome=nome.strip())
        session.add(p)
    p.nome = nome.strip()
    p.alias = [a.strip() for a in alias.split(",") if a.strip()]
    p.descrizione = descrizione.strip()
    p.attivo = bool(attivo)
    flash(request, f"Prodotto '{p.nome}' salvato.")
    return redirect("/impostazioni?scheda=prodotti")


@router.post("/impostazioni/utenti", dependencies=[Depends(verifica_csrf)])
def utente_salva(request: Request, user_id: str = Form(""), email: str = Form(...), nome: str = Form(""), ruolo: str = Form("membro"), attivo: str = Form("1"), riceve_digest: str = Form(""), session: Session = Depends(get_db), utente: User = Depends(admin_richiesto)):
    u = session.get(User, int(user_id)) if user_id else None
    if u is None:
        u = session.scalar(select(User).where(User.email == email.lower().strip()))
    if u is None:
        u = User(email=email.lower().strip())
        session.add(u)
    u.nome = nome.strip() or u.nome or u.email
    u.ruolo = ruolo if ruolo in ("admin", "membro") else "membro"
    u.attivo = bool(attivo)
    u.riceve_digest = bool(riceve_digest)
    if u.id == utente.id and not u.is_admin:
        u.ruolo = "admin"
    flash(request, f"Utente {u.email} salvato.")
    return redirect("/impostazioni?scheda=utenti")
