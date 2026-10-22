"""Digest giornaliero dei solleciti e degli elementi da verificare, via Gmail API o SMTP."""

from __future__ import annotations

import html
import logging
import smtplib
from dataclasses import dataclass, field
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from pmo.config import GMAIL_SEND, Settings, get_settings
from pmo.connectors.gmail import GmailClient
from pmo.connectors.google_oauth import credentials_per_account, scope_presente
from pmo.db.base import utcnow
from pmo.db.models import (
    Account,
    Documento,
    Messaggio,
    Pratica,
    Sollecito,
    StatoMessaggio,
    StatoSollecito,
    StatoVerifica,
    SyncRun,
    User,
)
from pmo.rules.engine import ordina_gravita
from pmo.services.impostazioni import get_impostazione

log = logging.getLogger(__name__)

ETICHETTE_GRAVITA = {"critico": "Critici", "avviso": "Avvisi", "info": "Informativi"}


@dataclass
class ContenutoDigest:
    oggetto: str
    testo: str
    html: str
    solleciti: list[Sollecito] = field(default_factory=list)
    contatori: dict[str, int] = field(default_factory=dict)


def _solleciti_aperti(session: Session, oggi: date) -> list[Sollecito]:
    righe = session.scalars(
        select(Sollecito)
        .options(selectinload(Sollecito.pratica).selectinload(Pratica.cliente))
        .where(Sollecito.stato.in_([StatoSollecito.APERTO.value, StatoSollecito.IN_CARICO.value]))
    ).all()
    righe = [s for s in righe if not (s.snooze_fino and s.snooze_fino > oggi)]
    righe.sort(key=lambda s: (ordina_gravita(s.gravita), s.notificato_il is not None, s.pratica.codice))
    return righe


def componi_digest(session: Session, settings: Settings | None = None, oggi: date | None = None) -> ContenutoDigest:
    settings = settings or get_settings()
    oggi = oggi or date.today()
    solleciti = _solleciti_aperti(session, oggi)
    da_rivedere_msg = session.scalar(select(func.count()).select_from(Messaggio).where(Messaggio.stato == StatoMessaggio.DA_RIVEDERE.value)) or 0
    da_rivedere_doc = session.scalar(select(func.count()).select_from(Documento).where(Documento.stato == StatoMessaggio.DA_RIVEDERE.value)) or 0
    proposte = session.scalar(select(func.count()).select_from(Pratica).where(Pratica.stato_verifica == StatoVerifica.PROPOSTO.value)) or 0
    nuovi = [s for s in solleciti if s.notificato_il is None]
    contatori = {
        "solleciti": len(solleciti),
        "nuovi": len(nuovi),
        "critici": sum(1 for s in solleciti if s.gravita == "critico"),
        "da_rivedere": int(da_rivedere_msg) + int(da_rivedere_doc),
        "pratiche_proposte": int(proposte),
    }
    base = settings.base_url.rstrip("/")
    oggetto = f"[PMO] {oggi.strftime('%d/%m/%Y')}: {contatori['solleciti']} solleciti aperti ({contatori['nuovi']} nuovi), {contatori['da_rivedere']} elementi da verificare"

    righe_txt: list[str] = [f"Digest PMO del {oggi.strftime('%d/%m/%Y')}", ""]
    righe_html: list[str] = [f"<h2>Digest PMO del {oggi.strftime('%d/%m/%Y')}</h2>"]
    righe_txt.append(
        f"Solleciti aperti: {contatori['solleciti']} (nuovi: {contatori['nuovi']}, critici: {contatori['critici']}). "
        f"Da verificare: {contatori['da_rivedere']} messaggi/documenti, {contatori['pratiche_proposte']} pratiche proposte."
    )
    righe_html.append(
        f"<p>Solleciti aperti: <b>{contatori['solleciti']}</b> (nuovi: {contatori['nuovi']}, critici: {contatori['critici']}). "
        f"Da verificare: <b>{contatori['da_rivedere']}</b> messaggi/documenti, <b>{contatori['pratiche_proposte']}</b> pratiche proposte "
        f"&rarr; <a href='{base}/revisione'>coda di revisione</a>.</p>"
    )
    gravita_corrente = None
    for s in solleciti:
        if s.gravita != gravita_corrente:
            gravita_corrente = s.gravita
            etichetta = ETICHETTE_GRAVITA.get(s.gravita, s.gravita)
            righe_txt += ["", f"== {etichetta} =="]
            righe_html.append(f"<h3>{html.escape(etichetta)}</h3><ul>")
        pr = s.pratica
        cliente = f" · {pr.cliente.nome}" if pr.cliente else ""
        nuovo = " [NUOVO]" if s.notificato_il is None else ""
        righe_txt.append(f"- {pr.codice} {pr.titolo}{cliente}: {s.titolo}{nuovo}\n  {s.messaggio}\n  {base}/pratiche/{pr.id}")
        righe_html.append(
            f"<li><a href='{base}/pratiche/{pr.id}'>{html.escape(pr.codice)} {html.escape(pr.titolo)}</a>{html.escape(cliente)}: "
            f"<b>{html.escape(s.titolo)}</b>{nuovo}<br><small>{html.escape(s.messaggio)}</small></li>"
        )
        if s is solleciti[-1] or solleciti[solleciti.index(s) + 1].gravita != s.gravita:
            righe_html.append("</ul>")
    if not solleciti:
        righe_txt.append("Nessun sollecito aperto.")
        righe_html.append("<p>Nessun sollecito aperto.</p>")
    righe_txt += ["", f"Cruscotto: {base}/"]
    righe_html.append(f"<p><a href='{base}/'>Apri il cruscotto PMO</a></p>")
    return ContenutoDigest(oggetto=oggetto, testo="\n".join(righe_txt), html="\n".join(righe_html), solleciti=solleciti, contatori=contatori)


def destinatari_digest(session: Session, settings: Settings | None = None) -> list[str]:
    settings = settings or get_settings()
    if settings.digest_recipients:
        return list(settings.digest_recipients)
    cfg = get_impostazione(session, "digest")
    if cfg.get("destinatari"):
        return [d.lower() for d in cfg["destinatari"]]
    utenti = session.scalars(select(User).where(User.attivo.is_(True), User.riceve_digest.is_(True))).all()
    return [u.email for u in utenti]


def _invia_smtp(settings: Settings, destinatari: list[str], contenuto: ContenutoDigest) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = contenuto.oggetto
    msg["From"] = settings.smtp_from or settings.smtp_user or "pmo@localhost"
    msg["To"] = ", ".join(destinatari)
    msg.attach(MIMEText(contenuto.testo, "plain", "utf-8"))
    msg.attach(MIMEText(contenuto.html, "html", "utf-8"))
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_user and settings.smtp_password:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.sendmail(msg["From"], destinatari, msg.as_string())


def _account_mittente(session: Session) -> Account | None:
    for account in session.scalars(select(Account).where(Account.attivo.is_(True))).all():
        if account.collegato and scope_presente(account, GMAIL_SEND):
            return account
    return None


def invia_digest(
    session: Session,
    settings: Settings | None = None,
    *,
    destinatari: list[str] | None = None,
    solo_anteprima: bool = False,
) -> dict:
    settings = settings or get_settings()
    run = SyncRun(tipo="digest")
    session.add(run)
    session.flush()
    contenuto = componi_digest(session, settings)
    destinatari = destinatari or destinatari_digest(session, settings)
    esito: dict = {"oggetto": contenuto.oggetto, "destinatari": destinatari, "contatori": contenuto.contatori, "inviato": False}
    if solo_anteprima:
        esito["testo"] = contenuto.testo
        run.stato = "ok"
        run.contatori = {**contenuto.contatori, "anteprima": True}
        run.finished_at = utcnow()
        session.commit()
        return esito
    try:
        if not destinatari:
            raise RuntimeError("Nessun destinatario configurato per il digest")
        account = _account_mittente(session)
        if account is not None:
            client = GmailClient(credentials_per_account(account, settings))
            client.send_email(destinatari, contenuto.oggetto, contenuto.testo, contenuto.html)
            esito["canale"] = f"gmail:{account.email}"
        elif settings.smtp_host:
            _invia_smtp(settings, destinatari, contenuto)
            esito["canale"] = "smtp"
        else:
            raise RuntimeError(
                "Nessun canale di invio: collegare una casella con scope gmail.send (PMO_GMAIL_SEND_SCOPE=true) oppure configurare SMTP"
            )
        adesso = utcnow()
        for s in contenuto.solleciti:
            s.notificato_il = adesso
        esito["inviato"] = True
        run.stato = "ok"
    except Exception as exc:  # noqa: BLE001
        log.exception("Invio digest fallito")
        esito["errore"] = str(exc)
        run.stato = "errore"
        run.errori = [str(exc)]
    run.contatori = {**contenuto.contatori, "destinatari": len(destinatari)}
    run.finished_at = utcnow()
    session.commit()
    return esito
