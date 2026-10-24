"""Sincronizzazione Gmail: importazione dei messaggi, filtri, collegamento e classificazione per thread."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from pmo.config import Settings, get_settings
from pmo.connectors.gmail import (
    GmailClient,
    HistoryScaduta,
    MessaggioParsato,
    gmail_query_finestra,
    parse_message,
)
from pmo.connectors.google_oauth import credentials_per_account
from pmo.db.base import utcnow
from pmo.db.models import Account, Messaggio, Pratica, StatoMessaggio, StatoPratica, SyncRun
from pmo.ingest.catalogo import Catalogo, carica_catalogo
from pmo.ingest.classifier import Classificatore, ErroreClassificazione, crea_classificatore
from pmo.ingest.filters import FiltriRumore, strip_quoted, tronca
from pmo.ingest.linker import collega_messaggio
from pmo.ingest.serie_errori import MOTIVO_INTERRUZIONE, SERIE_ERRORI_MAX, annulla_tentativi
from pmo.ingest.text_extract import estrai_testo
from pmo.services.codici import estrai_codice
from pmo.services.impostazioni import filtri_rumore
from pmo.services.pratiche import trova_per_codice

log = logging.getLogger(__name__)

MAX_ALLEGATI_ESTRATTI = 3
MAX_TENTATIVI_CLASSIFICAZIONE = 3
MAX_ID_FINESTRA = 5000  # id elencati per ogni giro in modalità finestra (i più recenti per primi)


# ---------------------------------------------------------------------------------------------
# Importazione
# ---------------------------------------------------------------------------------------------


def _ids_gia_presenti(session: Session, account_id: int, ids: list[str]) -> set[str]:
    presenti: set[str] = set()
    for i in range(0, len(ids), 500):
        chunk = ids[i : i + 500]
        presenti.update(
            session.scalars(
                select(Messaggio.gmail_message_id).where(
                    Messaggio.account_id == account_id, Messaggio.gmail_message_id.in_(chunk)
                )
            ).all()
        )
    return presenti


def pratica_del_thread(session: Session, account_id: int, thread_id: str) -> Pratica | None:
    """Pratica a cui il thread è già collegato con un collegamento affidabile."""
    righe = session.scalars(
        select(Messaggio)
        .where(
            Messaggio.account_id == account_id,
            Messaggio.gmail_thread_id == thread_id,
            Messaggio.pratica_id.isnot(None),
        )
        .order_by(Messaggio.data.desc())
    ).all()
    for m in righe:
        if m.link_origine in ("tag", "thread", "manuale") or (
            m.link_origine == "ai" and m.stato == StatoMessaggio.CLASSIFICATO
        ):
            if m.pratica and m.pratica.stato != StatoPratica.ANNULLATA:
                return m.pratica
    return None


def _prelinka(session: Session, messaggio: Messaggio) -> None:
    """Collegamento deterministico: codice nell'oggetto, oppure thread già collegato."""
    codice = messaggio.tag_codice or estrai_codice(messaggio.subject)
    if codice:
        messaggio.tag_codice = codice
        pratica = trova_per_codice(session, codice)
        if pratica is not None:
            messaggio.pratica_id = pratica.id
            messaggio.link_origine = "tag"
            return
    pratica = pratica_del_thread(session, messaggio.account_id, messaggio.gmail_thread_id)
    if pratica is not None:
        messaggio.pratica_id = pratica.id
        messaggio.link_origine = "thread"


def _estrai_allegati(client: GmailClient, parsed: MessaggioParsato, settings: Settings) -> str:
    testi: list[str] = []
    estratti = 0
    for allegato in parsed.attachments:
        if estratti >= MAX_ALLEGATI_ESTRATTI:
            break
        nome = allegato.filename.lower()
        if not (nome.endswith((".pdf", ".docx", ".txt")) or allegato.mime_type in ("application/pdf",)):
            continue
        if allegato.size > settings.attachment_max_mb * 1024 * 1024 or not allegato.attachment_id:
            continue
        try:
            data = client.get_attachment(parsed.gmail_message_id, allegato.attachment_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("Allegato %s non scaricabile: %s", allegato.filename, exc)
            continue
        testo = estrai_testo(data, allegato.mime_type, allegato.filename, max_chars=4000)
        if testo:
            testi.append(f"=== Allegato: {allegato.filename} ===\n{testo}")
            estratti += 1
    return "\n\n".join(testi)


def importa_messaggi(
    session: Session,
    account: Account,
    client: GmailClient,
    parsed_list: list[MessaggioParsato],
    filtri: FiltriRumore,
    settings: Settings,
) -> dict[str, int]:
    contatori = {"nuovi": 0, "ignorati": 0, "con_tag": 0}
    for parsed in parsed_list:
        tag = estrai_codice(parsed.subject)
        motivo = filtri.motivo_esclusione(
            from_email=parsed.from_email,
            subject=parsed.subject,
            labels=parsed.labels,
            has_list_unsubscribe=parsed.has_list_unsubscribe,
            tag_presente=bool(tag),
        )
        corpo = tronca(strip_quoted(parsed.body_text), settings.body_max_chars)
        interno = parsed.from_email == account.email.lower() or any(
            parsed.from_email.endswith("@" + d) for d in settings.internal_domains
        )
        messaggio = Messaggio(
            account_id=account.id,
            gmail_message_id=parsed.gmail_message_id,
            gmail_thread_id=parsed.gmail_thread_id,
            message_id_header=(parsed.message_id_header or "")[:500] or None,
            subject=parsed.subject[:1000],
            from_email=parsed.from_email[:255],
            from_name=parsed.from_name[:255],
            to_emails=parsed.to,
            cc_emails=parsed.cc,
            data=parsed.data,
            snippet=parsed.snippet,
            body_text=corpo,
            labels=parsed.labels,
            has_attachments=bool(parsed.attachments),
            attachments=[a.to_dict() for a in parsed.attachments],
            inviato_da_noi=interno,
            tag_codice=tag,
        )
        if motivo:
            messaggio.stato = StatoMessaggio.IGNORATO
            messaggio.motivo = motivo
            messaggio.processed_at = utcnow()
            contatori["ignorati"] += 1
        else:
            messaggio.stato = StatoMessaggio.NUOVO
            if settings.extract_attachments and parsed.attachments:
                messaggio.attachments_text = _estrai_allegati(client, parsed, settings)
            contatori["nuovi"] += 1
            if tag:
                contatori["con_tag"] += 1
        session.add(messaggio)
        session.flush()
        if messaggio.stato == StatoMessaggio.NUOVO:
            _prelinka(session, messaggio)
    return contatori


def sincronizza_gmail(
    session: Session,
    account: Account,
    settings: Settings | None = None,
    *,
    completa: bool = False,
    giorni: int | None = None,
    max_messaggi: int | None = None,
) -> SyncRun:
    """Scarica i messaggi nuovi della casella (history incrementale o finestra temporale)."""
    settings = settings or get_settings()
    run = SyncRun(account_id=account.id, tipo="gmail")
    session.add(run)
    session.flush()
    try:
        creds = credentials_per_account(account, settings)
        client = GmailClient(creds)
        profilo = client.profile()
        history_corrente = str(profilo.get("historyId") or "")
        filtri = filtri_rumore(session, settings)
        limite = max_messaggi or settings.max_messages_per_run

        ids: list[str] = []
        modalita = "finestra"
        history_scaduta = False
        if account.gmail_history_id and not completa:
            try:
                ids, _ = client.history_new_message_ids(account.gmail_history_id)
                modalita = "history"
            except HistoryScaduta:
                history_scaduta = True
                log.info("History Gmail scaduta per %s: ripiego sulla finestra temporale", account.email)
        if modalita == "finestra":
            adesso = datetime.now(UTC)
            if giorni:
                da = adesso - timedelta(days=giorni)
            elif history_scaduta and account.gmail_last_sync_at:
                da = account.gmail_last_sync_at - timedelta(days=2)
            elif completa or not account.gmail_sync_from:
                da = adesso - timedelta(days=settings.sync_window_days)
            else:
                # importazione iniziale ancora in corso: si riparte dalla stessa finestra
                da = datetime.combine(account.gmail_sync_from, time.min, tzinfo=UTC)
            query = gmail_query_finestra(da, account.query_filter)
            ids = client.list_message_ids(query, max_results=max(limite * 10, MAX_ID_FINESTRA))
            account.gmail_sync_from = da.date()

        presenti = _ids_gia_presenti(session, account.id, ids)
        da_scaricare = [i for i in ids if i not in presenti][:limite]
        run.contatori = {"modalita": modalita, "trovati": len(ids), "gia_presenti": len(presenti), "da_scaricare": len(da_scaricare)}

        contatori_tot = {"nuovi": 0, "ignorati": 0, "con_tag": 0}
        for i in range(0, len(da_scaricare), 50):
            chunk = da_scaricare[i : i + 50]
            raw_list = client.get_messages(chunk)
            parsed_list = []
            for raw in raw_list:
                try:
                    parsed_list.append(parse_message(raw))
                except Exception as exc:  # noqa: BLE001
                    run.errori = [*run.errori, f"parse {raw.get('id')}: {exc}"]
            c = importa_messaggi(session, account, client, parsed_list, filtri, settings)
            for k, v in c.items():
                contatori_tot[k] += v
            session.commit()

        # Il history id letto all'inizio copre tutto ciò che abbiamo scaricato; se abbiamo troncato
        # per limite, restiamo in modalità finestra finché non abbiamo recuperato tutto.
        if len(da_scaricare) == len([i for i in ids if i not in presenti]):
            account.gmail_history_id = history_corrente or account.gmail_history_id
        else:
            account.gmail_history_id = None
        account.gmail_last_sync_at = utcnow()
        account.last_sync_status = "ok"
        account.last_error = None
        run.contatori.update(contatori_tot)
        run.stato = "ok"
    except Exception as exc:  # noqa: BLE001
        log.exception("Sincronizzazione Gmail fallita per %s", account.email)
        run.stato = "errore"
        run.errori = [*run.errori, str(exc)]
        account.last_sync_status = "errore"
        account.last_error = str(exc)[:2000]
    finally:
        run.finished_at = utcnow()
        session.commit()
    return run


# ---------------------------------------------------------------------------------------------
# Classificazione
# ---------------------------------------------------------------------------------------------


def _contesto_thread(session: Session, account: Account, thread_id: str, esclusi: set[int]) -> str:
    precedenti = session.scalars(
        select(Messaggio)
        .where(Messaggio.account_id == account.id, Messaggio.gmail_thread_id == thread_id, Messaggio.id.notin_(esclusi))
        .order_by(Messaggio.data)
    ).all()
    if not precedenti:
        return ""
    righe = ["Messaggi precedenti dello stesso thread (già elaborati):"]
    for m in precedenti[-8:]:
        pratica = f" [collegato a {m.pratica.codice}]" if m.pratica_id and m.pratica else ""
        righe.append(f"- {m.data.date().isoformat()} da {m.from_email}: {m.subject[:100]}{pratica} — {m.snippet[:160]}")
    return "\n".join(righe)


def _prompt_thread(session: Session, account: Account, messaggi: list[Messaggio], pratica_prelinkata: Pratica | None) -> str:
    parti: list[str] = [f"Casella analizzata: {account.email}", f"Data odierna: {datetime.now(UTC).date().isoformat()}"]
    if pratica_prelinkata is not None:
        parti.append(
            f"Questo thread è già collegato alla pratica {pratica_prelinkata.codice} "
            f"({pratica_prelinkata.titolo}, stato {pratica_prelinkata.stato}): indica collegamento 'esistente' con quel codice "
            "e concentrati sugli eventi."
        )
    contesto = _contesto_thread(session, account, messaggi[0].gmail_thread_id, {m.id for m in messaggi})
    if contesto:
        parti.append(contesto)
    parti.append(f"\nMessaggi da classificare ({len(messaggi)}):")
    for m in messaggi:
        direzione = "INVIATO da noi" if m.inviato_da_noi else "RICEVUTO"
        parti.append(
            f"\n--- Messaggio id={m.gmail_message_id} ({direzione}) ---\n"
            f"Data: {m.data.isoformat()}\nDa: {m.from_name} <{m.from_email}>\nA: {', '.join(m.to_emails)}\n"
            f"Cc: {', '.join(m.cc_emails)}\nOggetto: {m.subject}\n"
            f"Allegati: {', '.join(a.get('filename', '') for a in m.attachments) or 'nessuno'}\n\n{m.body_text}"
        )
        if m.attachments_text:
            parti.append(f"\n{m.attachments_text}")
    return "\n".join(parti)


def classifica_messaggi(
    session: Session,
    account: Account,
    settings: Settings | None = None,
    *,
    classificatore: Classificatore | None = None,
    catalogo: Catalogo | None = None,
    limite: int | None = None,
) -> SyncRun:
    """Classifica i messaggi in stato 'nuovo' della casella, un thread alla volta."""
    settings = settings or get_settings()
    classificatore = classificatore or crea_classificatore(settings)
    catalogo = catalogo or carica_catalogo(session, settings)
    run = SyncRun(account_id=account.id, tipo="classify")
    session.add(run)
    session.flush()
    limite = limite or settings.max_messages_per_run
    in_attesa = session.scalars(
        select(Messaggio)
        .where(Messaggio.account_id == account.id, Messaggio.stato == StatoMessaggio.NUOVO)
        .order_by(Messaggio.data)
        .limit(limite)
    ).all()
    per_thread: dict[str, list[Messaggio]] = defaultdict(list)
    for m in in_attesa:
        per_thread[m.gmail_thread_id].append(m)

    contatori = {"messaggi": 0, "thread": 0, "classificati": 0, "da_rivedere": 0, "ignorati": 0, "errori": 0}
    catalogo_testo = catalogo.testo_prompt()
    serie: list[tuple[list[Messaggio], list]] = []  # errori temporanei consecutivi
    for thread_id, messaggi in per_thread.items():
        contatori["thread"] += 1
        contatori["messaggi"] += len(messaggi)
        prelinkata = next((m.pratica for m in messaggi if m.pratica_id and m.pratica), None)
        prompt = _prompt_thread(session, account, messaggi, prelinkata)
        try:
            risultato = classificatore.classifica_thread(catalogo_testo, prompt)
        except ErroreClassificazione as exc:
            contatori["errori"] += 1
            run.errori = [*run.errori, f"thread {thread_id}: {exc}"]
            precedenti = [m.classificazione for m in messaggi]
            if exc.temporaneo:
                serie.append((messaggi, precedenti))
            else:
                serie.clear()
            for m in messaggi:
                tentativi = int((m.classificazione or {}).get("tentativi", 0)) + 1
                m.classificazione = {"tentativi": tentativi, "ultimo_errore": str(exc)}
                if not exc.temporaneo or tentativi >= MAX_TENTATIVI_CLASSIFICAZIONE:
                    m.stato = StatoMessaggio.ERRORE
                    m.motivo = f"Classificazione fallita: {exc}"[:500]
            session.commit()
            if not exc.temporaneo and "IA disabilitata" in str(exc):
                break
            if len(serie) >= SERIE_ERRORI_MAX:
                annulla_tentativi(serie)
                run.errori = [*run.errori, MOTIVO_INTERRUZIONE]
                session.commit()
                break
            continue
        serie.clear()
        per_id = {r.id: r for r in risultato.messaggi}
        for m in messaggi:
            r = per_id.get(m.gmail_message_id)
            if r is None:
                m.stato = StatoMessaggio.DA_RIVEDERE
                m.motivo = "IA: nessun risultato per questo messaggio"
                m.processed_at = utcnow()
                contatori["da_rivedere"] += 1
                continue
            collega_messaggio(session, m, r, catalogo, settings)
            contatori[
                "classificati" if m.stato == StatoMessaggio.CLASSIFICATO else ("ignorati" if m.stato == StatoMessaggio.IGNORATO else "da_rivedere")
            ] += 1
        session.commit()
    uso = getattr(classificatore, "uso", None)
    if uso is not None:
        contatori["token"] = uso.to_dict()
    run.contatori = contatori
    run.stato = "ok" if contatori["errori"] == 0 else "errore"
    run.finished_at = utcnow()
    session.commit()
    return run
