"""Chi aspetta una risposta da chi, pratica per pratica: il cliente da noi, o noi dal cliente.

Il calcolo non usa l'IA: parte dagli eventi già estratti dalle mail e guarda la direzione dello scambio.
- `richieste_in_attesa`: il cliente ha scritto una richiesta (informazioni, specifiche, stima, sollecito) e sulla
  stessa pratica non risulta una nostra mail successiva a un destinatario esterno.
- `attese_cliente`: noi abbiamo scritto al cliente (offerta, stima, richiesta di informazioni o specifiche,
  sollecito) e non risulta né una sua mail successiva né un evento che dica che ha risposto (offerta accettata, ordine...).
Una mail solo interna (un inoltro a un collega) non vale come risposta. È una stima prudente: vede solo le caselle
collegate, quindi una risposta data a voce o da una casella non collegata non viene riconosciuta. Per questo
l'interfaccia la presenta come "da verificare".
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from pmo.config import get_settings
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
    "risposta": "Il cliente aspetta una nostra risposta",
    "attesa_cliente": "Noi aspettiamo una risposta del cliente",
    "attese": "In attesa di una risposta, in entrambi i sensi",
    "solleciti": "Con solleciti aperti",
    "scadenza": "Scadenza superata o vicina",
    "qualsiasi": "Qualsiasi azione da fare",
}

# Cliente -> noi: eventi che, in una mail del cliente, chiedono qualcosa a La Traccia.
TIPI_RICHIESTA: tuple[str, ...] = (
    TipoEvento.RICHIESTA_INFORMAZIONI.value,
    TipoEvento.SPECIFICHE_RICHIESTE.value,
    TipoEvento.STIMA_RICHIESTA.value,
    TipoEvento.SOLLECITO_RICEVUTO.value,
)

# Noi -> cliente: eventi che, in una nostra mail, restano in attesa di una risposta del cliente.
TIPI_ATTESA_CLIENTE: tuple[str, ...] = (
    TipoEvento.OFFERTA_INVIATA.value,
    TipoEvento.STIMA_INVIATA.value,
    TipoEvento.SPECIFICHE_INVIATE.value,
    TipoEvento.RICHIESTA_INFORMAZIONI.value,
    TipoEvento.SPECIFICHE_RICHIESTE.value,
    TipoEvento.SOLLECITO_INVIATO.value,
)

# Eventi che dicono che il cliente ha risposto, anche quando la risposta non è una mail (un ordine su Drive, ad esempio).
TIPI_RISPOSTA_CLIENTE: tuple[str, ...] = (
    TipoEvento.OFFERTA_ACCETTATA.value,
    TipoEvento.OFFERTA_RIFIUTATA.value,
    TipoEvento.ORDINE_RICEVUTO.value,
    TipoEvento.SPECIFICHE_RICEVUTE.value,
    TipoEvento.PAGAMENTO_RICEVUTO.value,
    TipoEvento.SAL_FIRMATO.value,
    TipoEvento.COLLAUDO.value,
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
    controparte: str = ""  # il cliente: chi ha scritto (richieste) o a chi abbiamo scritto (attese)


def _in_utc(valore: datetime) -> datetime:
    return valore if valore.tzinfo is not None else valore.replace(tzinfo=UTC)


def _esterni(indirizzi: Iterable[str | None], domini_interni: set[str]) -> list[str]:
    return [a for a in indirizzi if a and a.rsplit("@", 1)[-1].lower() not in domini_interni]


def _scambi(
    session: Session, ids: list[int] | None, *, tipi: tuple[str, ...], da_noi: bool
) -> dict[int, list[RichiestaInAttesa]]:
    """Mail con un evento di `tipi`, nella direzione indicata, a cui l'altra parte non ha ancora risposto."""
    domini = {d.lower() for d in get_settings().internal_domains}
    terminali = [s.value for s in STATI_TERMINALI]

    domanda = (
        select(Evento, Messaggio)
        .join(Messaggio, Evento.messaggio_id == Messaggio.id)
        .join(Pratica, Evento.pratica_id == Pratica.id)
        .where(
            Evento.tipo.in_(tipi),
            Evento.fonte_tipo == TipoFonte.EMAIL,
            Evento.stato_verifica != StatoVerifica.RIFIUTATO,
            Messaggio.inviato_da_noi.is_(da_noi),
            Messaggio.stato != StatoMessaggio.IGNORATO,
            Pratica.stato.not_in(terminali),
        )
        .order_by(Messaggio.data.desc())
    )
    # le mail della controparte: se la richiesta è del cliente rispondiamo noi, e viceversa
    risposte = select(Messaggio.pratica_id, Messaggio.data, Messaggio.from_email, Messaggio.to_emails, Messaggio.cc_emails).where(
        Messaggio.inviato_da_noi.is_(not da_noi), Messaggio.pratica_id.is_not(None), Messaggio.stato != StatoMessaggio.IGNORATO
    )
    eventi_risposta = select(Evento.pratica_id, func.max(Evento.data_evento)).where(
        Evento.tipo.in_(TIPI_RISPOSTA_CLIENTE),
        Evento.fonte_tipo != TipoFonte.SISTEMA,
        Evento.stato_verifica != StatoVerifica.RIFIUTATO,
    )
    if ids is not None:
        domanda = domanda.where(Evento.pratica_id.in_(ids))
        risposte = risposte.where(Messaggio.pratica_id.in_(ids))
        eventi_risposta = eventi_risposta.where(Evento.pratica_id.in_(ids))

    ultima_risposta: dict[int, datetime] = {}
    for pratica_id, data, _mittente, a, cc in session.execute(risposte):
        if da_noi:
            valida = True  # il cliente ci scrive: è già un indirizzo esterno
        else:
            valida = bool(_esterni([*(a or []), *(cc or [])], domini))  # una mail solo interna non è una risposta
        if valida and data and (pratica_id not in ultima_risposta or _in_utc(data) > ultima_risposta[pratica_id]):
            ultima_risposta[pratica_id] = _in_utc(data)
    if da_noi:
        for pratica_id, data in session.execute(eventi_risposta.group_by(Evento.pratica_id)):
            if data and (pratica_id not in ultima_risposta or _in_utc(data) > ultima_risposta[pratica_id]):
                ultima_risposta[pratica_id] = _in_utc(data)

    adesso = utcnow()
    per_pratica: dict[int, dict[int, RichiestaInAttesa]] = {}
    for evento, messaggio in session.execute(domanda):
        data = _in_utc(messaggio.data)
        esterni = _esterni([*(messaggio.to_emails or []), *(messaggio.cc_emails or [])], domini)
        if da_noi and not esterni:
            continue  # una nostra mail solo interna non aspetta nessuna risposta dal cliente
        risposta = ultima_risposta.get(evento.pratica_id)
        if risposta is not None and risposta > data:
            continue
        controparte = (messaggio.from_name or messaggio.from_email) if not da_noi else (esterni[0] if esterni else "")
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
                controparte=controparte,
            ),
        )
    return {pid: list(richieste.values()) for pid, richieste in per_pratica.items()}


def richieste_in_attesa(session: Session, pratica_ids: Iterable[int] | None = None) -> dict[int, list[RichiestaInAttesa]]:
    """Per ogni pratica attiva, le richieste del cliente più recenti senza una nostra risposta successiva."""
    ids = list(pratica_ids) if pratica_ids is not None else None
    if ids is not None and not ids:
        return {}
    return _scambi(session, ids, tipi=TIPI_RICHIESTA, da_noi=False)


def attese_cliente(session: Session, pratica_ids: Iterable[int] | None = None) -> dict[int, list[RichiestaInAttesa]]:
    """Per ogni pratica attiva, ciò che abbiamo chiesto o inviato al cliente e che aspetta ancora una sua risposta."""
    ids = list(pratica_ids) if pratica_ids is not None else None
    if ids is not None and not ids:
        return {}
    return _scambi(session, ids, tipi=TIPI_ATTESA_CLIENTE, da_noi=True)


def pratiche_con_azioni(
    session: Session,
    richieste: dict[int, list[RichiestaInAttesa]] | None = None,
    attese: dict[int, list[RichiestaInAttesa]] | None = None,
) -> dict[str, set[int]]:
    """Gli identificativi delle pratiche con qualcosa in sospeso, divisi per motivo.

    - `risposta`: il cliente ha scritto una richiesta e non risulta una nostra mail successiva;
    - `attesa_cliente`: abbiamo scritto noi e non risulta una risposta del cliente;
    - `attese`: l'unione dei due, cioè tutto ciò che aspetta una risposta in un senso o nell'altro;
    - `solleciti`: c'è almeno un sollecito aperto o in carico e non rimandato a una data futura;
    - `scadenza`: vedi `scadenze_vicine`.
    `qualsiasi` è ciò che spetta a noi: risposta, solleciti e scadenze (non l'attesa del cliente).
    Le pratiche chiuse o annullate non contano.
    """
    oggi = date.today()
    terminali = [s.value for s in STATI_TERMINALI]
    risposta = set(richieste if richieste is not None else richieste_in_attesa(session))
    attesa_cliente = set(attese if attese is not None else attese_cliente(session))
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
    return {
        "risposta": risposta,
        "attesa_cliente": attesa_cliente,
        "attese": risposta | attesa_cliente,
        "solleciti": solleciti,
        "scadenza": scadenza,
        "qualsiasi": risposta | solleciti | scadenza,
    }


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
