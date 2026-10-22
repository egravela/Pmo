"""Caricamento delle anagrafiche iniziali da config/seed.yaml (idempotente)."""

from __future__ import annotations

from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from pmo.db.models import Cliente, Prodotto, User
from pmo.rules.definitions import assicura_regole


def percorso_seed_default() -> Path:
    """config/seed.yaml nel sorgente (installazione editable) oppure nella cartella corrente."""
    for base in (Path(__file__).resolve().parents[3], Path.cwd()):
        candidato = base / "config" / "seed.yaml"
        if candidato.exists():
            return candidato
    raise FileNotFoundError("config/seed.yaml non trovato: indicare il file con --file")


def carica_seed(session: Session, percorso: Path | None = None) -> dict[str, int]:
    percorso = percorso or percorso_seed_default()
    dati = yaml.safe_load(percorso.read_text(encoding="utf-8")) or {}
    contatori = {"utenti": 0, "prodotti": 0, "clienti": 0, "regole": 0}

    for spec in dati.get("utenti", []) or []:
        email = spec["email"].strip().lower()
        utente = session.scalar(select(User).where(User.email == email))
        if utente is None:
            utente = User(email=email)
            session.add(utente)
            contatori["utenti"] += 1
        utente.nome = spec.get("nome") or utente.nome or email
        if spec.get("ruolo"):
            utente.ruolo = spec["ruolo"]

    for spec in dati.get("prodotti", []) or []:
        nome = spec["nome"].strip()
        prodotto = session.scalar(select(Prodotto).where(Prodotto.nome == nome))
        if prodotto is None:
            prodotto = Prodotto(nome=nome)
            session.add(prodotto)
            contatori["prodotti"] += 1
        prodotto.alias = list(spec.get("alias") or [])
        prodotto.descrizione = spec.get("descrizione") or ""

    for spec in dati.get("clienti", []) or []:
        nome = spec["nome"].strip()
        cliente = session.scalar(select(Cliente).where(Cliente.nome == nome))
        if cliente is None:
            cliente = Cliente(nome=nome)
            session.add(cliente)
            contatori["clienti"] += 1
        cliente.alias = list(spec.get("alias") or [])
        cliente.domini = [d.lower() for d in spec.get("domini") or []]
        cliente.tipo = spec.get("tipo") or "altro"

    contatori["regole"] = len(assicura_regole(session))
    session.commit()
    return contatori
