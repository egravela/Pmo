"""Contesto di dominio fornito al classificatore: clienti, prodotti, team e pratiche aperte."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from pmo.config import Settings, get_settings
from pmo.db.models import Account, Cliente, Pratica, Prodotto, StatoPratica, StatoVerifica, User
from pmo.ingest.filters import dominio

MAX_PRATICHE_IN_PROMPT = 200


@dataclass
class Catalogo:
    clienti: list[Cliente]
    prodotti: list[Prodotto]
    team: list[tuple[str, str]]  # (nome, email)
    pratiche: list[Pratica]
    domini_interni: list[str]
    caselle: list[str] = field(default_factory=list)

    # --- lookup ---------------------------------------------------------------------------------
    def cliente_per_dominio(self, email: str | None) -> Cliente | None:
        dom = dominio(email)
        if not dom:
            return None
        for cliente in self.clienti:
            for d in cliente.domini or []:
                d = d.lower()
                if dom == d or dom.endswith("." + d):
                    return cliente
        return None

    def e_interno(self, email: str | None) -> bool:
        dom = dominio(email)
        return any(dom == d or dom.endswith("." + d) for d in self.domini_interni)

    def pratica_per_codice(self, codice: str | None) -> Pratica | None:
        if not codice:
            return None
        codice = codice.upper()
        for pratica in self.pratiche:
            if pratica.codice == codice:
                return pratica
        return None

    # --- rendering per il prompt ----------------------------------------------------------------
    def testo_prompt(self) -> str:
        righe: list[str] = ["## Clienti noti (nome | alias | domini email)"]
        for c in self.clienti:
            alias = ", ".join(c.alias or []) or "-"
            domini = ", ".join(c.domini or []) or "-"
            righe.append(f"- {c.nome} | {alias} | {domini}")
        righe.append("\n## Prodotti e soluzioni La Traccia (nome | alias | descrizione)")
        for p in self.prodotti:
            alias = ", ".join(p.alias or []) or "-"
            righe.append(f"- {p.nome} | {alias} | {p.descrizione or '-'}")
        righe.append("\n## Team interno (nome | email)")
        for nome, email in self.team:
            righe.append(f"- {nome} | {email}")
        righe.append(f"\nDomini interni: {', '.join(self.domini_interni)}")
        righe.append("\n## Pratiche aperte (codice | titolo | cliente | prodotto | stato | ultimo evento | riferimenti)")
        if not self.pratiche:
            righe.append("- (nessuna pratica registrata finora)")
        for pr in self.pratiche:
            cliente = pr.cliente.nome if pr.cliente else "-"
            prodotto = pr.prodotto.nome if pr.prodotto else "-"
            ultimo = pr.ultimo_evento_at.date().isoformat() if pr.ultimo_evento_at else "-"
            rif = "; ".join(f"{k}={v}" for k, v in (pr.riferimenti or {}).items() if v) or "-"
            verifica = "" if pr.stato_verifica == StatoVerifica.CONFERMATO else " (proposta, da confermare)"
            righe.append(f"- {pr.codice} | {pr.titolo} | {cliente} | {prodotto} | {pr.stato}{verifica} | {ultimo} | {rif}")
        return "\n".join(righe)


def carica_catalogo(session: Session, settings: Settings | None = None) -> Catalogo:
    settings = settings or get_settings()
    clienti = list(session.scalars(select(Cliente).where(Cliente.attivo.is_(True)).order_by(Cliente.nome)).all())
    prodotti = list(session.scalars(select(Prodotto).where(Prodotto.attivo.is_(True)).order_by(Prodotto.nome)).all())
    utenti = session.scalars(select(User).where(User.attivo.is_(True)).order_by(User.nome)).all()
    team = [(u.nome or u.email, u.email) for u in utenti]
    caselle = [a.email for a in session.scalars(select(Account)).all()]
    for email in caselle:
        if email not in {e for _, e in team}:
            team.append((email, email))
    pratiche = list(
        session.scalars(
            select(Pratica)
            .options(selectinload(Pratica.cliente), selectinload(Pratica.prodotto))
            .where(
                Pratica.stato.notin_([StatoPratica.CHIUSA.value, StatoPratica.ANNULLATA.value]),
                Pratica.stato_verifica != StatoVerifica.RIFIUTATO.value,
            )
            .order_by(Pratica.ultimo_evento_at.desc().nullslast(), Pratica.id.desc())
            .limit(MAX_PRATICHE_IN_PROMPT)
        ).all()
    )
    return Catalogo(
        clienti=clienti,
        prodotti=prodotti,
        team=team,
        pratiche=pratiche,
        domini_interni=list(settings.internal_domains),
        caselle=caselle,
    )
