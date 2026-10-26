"""Richieste espresse dai clienti verso La Traccia che non risultano ancora evase.

Il calcolo non usa l'IA: parte dagli eventi già estratti (richiesta di informazioni, di specifiche, di stima,
sollecito ricevuto) e tiene quelli che arrivano da una mail del cliente a cui non è seguita, sulla stessa pratica,
nessuna mail inviata da noi. È una stima prudente: vede solo le caselle collegate, quindi una risposta data a voce
o da una casella non collegata non viene riconosciuta. Per questo l'interfaccia la presenta come "da verificare".
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from pmo.db.base import utcnow
from pmo.db.models import (
    STATI_TERMINALI,
    Evento,
    Messaggio,
    Pratica,
    Sollecito,
    StatoMessaggio,
    StatoSollecito,
    StatoVerifica,
    TipoEvento,
    TipoFonte,
)

GIORNI_SCADENZA_VICINA = 14
REGOLA_VERIFICA = "da_verificare"  # sollecito che chiede di confermare una pratica o un evento proposto dall'IA

# Le scelte del filtro "Azioni da fare" dell'elenco pratiche: valore -> etichetta.
AZIONI_DA_FARE: dict[str, str] = {
    "risposta": "In attesa di una nostra risposta",
    "solleciti": "Con solleciti aperti",
    "scadenza": "Scadenza superata o vicina",
    "qualsiasi": "Qualsiasi azione da fare",
}

TIPI_RICHIESTA: tuple[str, ...] = (
    TipoEvento.RICHIESTA_INFORMAZIONI.value,
    TipoEvento.SPECIFICHE_RICHIESTE.value,
    TipoEvento.STIMA_RICHIESTA.value,
    TipoEvento.SOLLECITO_RICEVUTO.value,
)


@dataclass(frozen=True)
class RichiestaInAttesa:
    pratica_id: int
    evento_id: int
    messaggio_id: int
    tipo: str
    titolo: str
    descrizione: str
    data: datetime
    mittente: str
    oggetto: str
    url: str | None
    giorni: int


def _in_utc(valore: datetime) -> datetime:
    return valore if valore.tzinfo is not None else valore.replace(tzinfo=UTC)


def richieste_in_attesa(session: Session, pratica_ids: Iterable[int] | None = None) -> dict[int, list[RichiestaInAttesa]]:
    """Per ogni pratica attiva, le richieste del cliente più recenti senza una nostra mail successiva."""
    ids = list(pratica_ids) if pratica_ids is not None else None
    if ids is not None and not ids:
        return {}

    domanda = (
        select(Evento, Messaggio)
        .join(Messaggio, Evento.messaggio_id == Messaggio.id)
        .join(Pratica, Evento.pratica_id == Pratica.id)
        .where(
            Evento.tipo.in_(TIPI_RICHIESTA),
            Evento.fonte_tipo == TipoFonte.EMAIL,
            Evento.stato_verifica != StatoVerifica.RIFIUTATO,
            Messaggio.inviato_da_noi.is_(False),
            Messaggio.stato != StatoMessaggio.IGNORATO,
            Pratica.stato.not_in([s.value for s in STATI_TERMINALI]),
        )
    )
    ultima_nostra = select(Messaggio.pratica_id, func.max(Messaggio.data)).where(
        Messaggio.inviato_da_noi.is_(True), Messaggio.pratica_id.is_not(None)
    )
    if ids is not None:
        domanda = domanda.where(Evento.pratica_id.in_(ids))
        ultima_nostra = ultima_nostra.where(Messaggio.pratica_id.in_(ids))
    nostre = {pid: _in_utc(d) for pid, d in session.execute(ultima_nostra.group_by(Messaggio.pratica_id)) if d}

    adesso = utcnow()
    per_pratica: dict[int, dict[int, RichiestaInAttesa]] = {}
    for evento, messaggio in session.execute(domanda.order_by(Messaggio.data.desc())):
        data = _in_utc(messaggio.data)
        risposta = nostre.get(evento.pratica_id)
        if risposta is not None and risposta > data:
            continue
        # una mail può contenere più richieste: se ne mostra una sola
        per_pratica.setdefault(evento.pratica_id, {}).setdefault(
            messaggio.id,
            RichiestaInAttesa(
                pratica_id=evento.pratica_id,
                evento_id=evento.id,
                messaggio_id=messaggio.id,
                tipo=evento.tipo,
                titolo=evento.titolo,
                descrizione=evento.descrizione or "",
                data=data,
                mittente=messaggio.from_name or messaggio.from_email,
                oggetto=messaggio.subject,
                url=messaggio.gmail_url,
                giorni=max((adesso - data).days, 0),
            ),
        )
    return {pid: list(richieste.values()) for pid, richieste in per_pratica.items()}


def pratiche_con_azioni(
    session: Session, richieste: dict[int, list[RichiestaInAttesa]] | None = None
) -> dict[str, set[int]]:
    """Gli identificativi delle pratiche per cui La Traccia deve ancora fare qualcosa, divisi per motivo.

    - `risposta`: il cliente ha scritto una richiesta e non risulta una nostra mail successiva;
    - `solleciti`: c'è almeno un sollecito aperto o in carico e non rimandato a una data futura;
    - `scadenza`: vedi `scadenze_vicine`.
    `qualsiasi` è l'unione dei tre. Le pratiche chiuse o annullate non contano.
    """
    oggi = date.today()
    terminali = [s.value for s in STATI_TERMINALI]
    risposta = set(richieste if richieste is not None else richieste_in_attesa(session))
    scadenza = set(scadenze_vicine(session))
    solleciti = set(
        session.scalars(
            select(Sollecito.pratica_id)
            .join(Pratica, Sollecito.pratica_id == Pratica.id)
            .where(
                Sollecito.stato.in_([StatoSollecito.APERTO.value, StatoSollecito.IN_CARICO.value]),
                # "da_verificare" ricorda di confermare le proposte dell'IA: è lavoro interno, non un'azione verso i clienti
                Sollecito.regola != REGOLA_VERIFICA,
                or_(Sollecito.snooze_fino.is_(None), Sollecito.snooze_fino <= oggi),
                Pratica.stato.not_in(terminali),
            )
            .distinct()
        )
    )
    return {"risposta": risposta, "solleciti": solleciti, "scadenza": scadenza, "qualsiasi": risposta | solleciti | scadenza}


def scadenze_vicine(session: Session) -> dict[int, date]:
    """Per ogni pratica attiva, la scadenza più urgente tra quelle già scadute o in arrivo.

    Conta la scadenza della pratica, anche se superata, e la prossima indicata da un evento, purché cada tra oggi e
    `GIORNI_SCADENZA_VICINA` giorni. Le scadenze passate degli eventi no: da una mail non si sa se siano state rispettate.
    Gli eventi ancora da verificare contano, perché la scadenza della pratica si aggiorna solo con quelli confermati.
    """
    oggi = date.today()
    limite = oggi + timedelta(days=GIORNI_SCADENZA_VICINA)
    terminali = [s.value for s in STATI_TERMINALI]
    scadenze: dict[int, date] = {
        pratica_id: giorno
        for pratica_id, giorno in session.execute(
            select(Pratica.id, Pratica.data_scadenza).where(
                Pratica.data_scadenza.is_not(None), Pratica.data_scadenza <= limite, Pratica.stato.not_in(terminali)
            )
        )
    }
    da_eventi = session.execute(
        select(Evento.pratica_id, func.min(Evento.scadenza))
        .join(Pratica, Evento.pratica_id == Pratica.id)
        .where(
            Evento.scadenza >= oggi,
            Evento.scadenza <= limite,
            Evento.stato_verifica != StatoVerifica.RIFIUTATO,
            Pratica.stato.not_in(terminali),
        )
        .group_by(Evento.pratica_id)
    )
    for pratica_id, giorno in da_eventi:
        if pratica_id not in scadenze or giorno < scadenze[pratica_id]:
            scadenze[pratica_id] = giorno
    return scadenze
