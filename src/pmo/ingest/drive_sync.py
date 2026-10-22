"""Sincronizzazione Google Drive: cartelle monitorate → documenti → collegamento alle pratiche."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from pmo.config import Settings, get_settings
from pmo.connectors.drive import DriveClient, FileDrive
from pmo.connectors.google_oauth import credentials_per_account
from pmo.db.base import utcnow
from pmo.db.models import Account, Documento, StatoMessaggio, SyncRun, WatchedFolder
from pmo.ingest.catalogo import Catalogo, carica_catalogo
from pmo.ingest.classifier import Classificatore, ErroreClassificazione, crea_classificatore
from pmo.ingest.linker import collega_documento
from pmo.services.codici import estrai_codice
from pmo.services.pratiche import trova_per_codice

log = logging.getLogger(__name__)

MIME_PERTINENTI_PREFISSI = ("application/pdf", "application/vnd.google-apps.document", "application/vnd.google-apps.spreadsheet", "application/vnd.google-apps.presentation", "text/")
ESTENSIONI_PERTINENTI = (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".txt", ".md", ".csv", ".odt", ".ods")
DOCUMENTI_PER_CHIAMATA = 8
MAX_TENTATIVI = 3


def _pertinente(file: FileDrive) -> bool:
    nome = file.nome.lower()
    return file.mime_type.startswith(MIME_PERTINENTI_PREFISSI) or nome.endswith(ESTENSIONI_PERTINENTI)


def _upsert_documento(session: Session, account: Account, folder: WatchedFolder, file: FileDrive, client: DriveClient) -> Documento | None:
    doc = session.scalar(
        select(Documento).where(Documento.account_id == account.id, Documento.drive_file_id == file.id)
    )
    nuovo = doc is None
    if doc is None:
        doc = Documento(account_id=account.id, drive_file_id=file.id, nome=file.nome)
        session.add(doc)
    modificato = nuovo or (file.modified_time and doc.modified_time and file.modified_time > doc.modified_time)
    doc.watched_folder_id = folder.id
    doc.nome = file.nome[:500]
    doc.mime_type = file.mime_type[:255]
    doc.percorso = file.percorso[:1000]
    doc.parent_folder_id = file.parent_id
    doc.web_view_link = file.web_view_link
    doc.dimensione = file.size
    doc.modified_time = file.modified_time
    doc.created_time = file.created_time
    doc.ultimo_autore = file.ultimo_autore[:255]
    if not modificato:
        return None
    tag = estrai_codice(file.nome) or estrai_codice(file.percorso)
    doc.tag_codice = tag
    if not _pertinente(file):
        doc.stato = StatoMessaggio.IGNORATO
        doc.motivo = "tipo di file non pertinente"
        doc.processed_at = utcnow()
        return doc
    doc.estratto = client.estratto_testo(file, max_chars=4000)
    doc.stato = StatoMessaggio.NUOVO
    doc.motivo = ""
    doc.processed_at = None
    if tag:
        pratica = trova_per_codice(session, tag)
        if pratica is not None:
            doc.pratica_id = pratica.id
            doc.link_origine = "tag"
    session.flush()
    return doc


def sincronizza_drive(
    session: Session,
    account: Account,
    settings: Settings | None = None,
    *,
    completa: bool = False,
) -> SyncRun:
    settings = settings or get_settings()
    run = SyncRun(account_id=account.id, tipo="drive")
    session.add(run)
    session.flush()
    contatori = {"cartelle": 0, "file_visti": 0, "nuovi_o_modificati": 0, "ignorati": 0}
    try:
        creds = credentials_per_account(account, settings)
        client = DriveClient(creds)
        cartelle = [f for f in account.watched_folders if f.attivo]
        for folder in cartelle:
            contatori["cartelle"] += 1
            soglia = None if completa or not folder.last_sync_at else folder.last_sync_at - timedelta(hours=1)
            for file in client.walk(folder.drive_folder_id, folder.nome or "", ricorsivo=folder.ricorsivo):
                contatori["file_visti"] += 1
                if soglia and file.modified_time and file.modified_time <= soglia:
                    continue
                doc = _upsert_documento(session, account, folder, file, client)
                if doc is None:
                    continue
                if doc.stato == StatoMessaggio.IGNORATO:
                    contatori["ignorati"] += 1
                else:
                    contatori["nuovi_o_modificati"] += 1
            folder.last_sync_at = utcnow()
            session.commit()
        account.drive_last_sync_at = utcnow()
        run.stato = "ok"
    except Exception as exc:  # noqa: BLE001
        log.exception("Sincronizzazione Drive fallita per %s", account.email)
        run.stato = "errore"
        run.errori = [*run.errori, str(exc)]
        account.last_error = str(exc)[:2000]
    finally:
        run.contatori = contatori
        run.finished_at = utcnow()
        session.commit()
    return run


def _prompt_documenti(account: Account, documenti: list[Documento]) -> str:
    parti = [f"Casella/Drive analizzato: {account.email}", f"Data odierna: {datetime.now(UTC).date().isoformat()}", f"\nDocumenti da classificare ({len(documenti)}):"]
    for d in documenti:
        pre = f"\nGià collegato alla pratica {d.pratica.codice}: indica collegamento 'esistente'." if d.pratica_id and d.pratica else ""
        parti.append(
            f"\n--- Documento id={d.drive_file_id} ---\nNome: {d.nome}\nPercorso: {d.percorso}\nTipo: {d.mime_type}\n"
            f"Modificato: {d.modified_time.isoformat() if d.modified_time else '-'} da {d.ultimo_autore or '-'}{pre}\n"
            f"Estratto:\n{d.estratto or '(nessun testo estraibile)'}"
        )
    return "\n".join(parti)


def classifica_documenti(
    session: Session,
    account: Account,
    settings: Settings | None = None,
    *,
    classificatore: Classificatore | None = None,
    catalogo: Catalogo | None = None,
    limite: int = 100,
) -> SyncRun:
    settings = settings or get_settings()
    classificatore = classificatore or crea_classificatore(settings)
    catalogo = catalogo or carica_catalogo(session, settings)
    run = SyncRun(account_id=account.id, tipo="classify_drive")
    session.add(run)
    session.flush()
    in_attesa = session.scalars(
        select(Documento)
        .where(Documento.account_id == account.id, Documento.stato == StatoMessaggio.NUOVO)
        .order_by(Documento.percorso, Documento.modified_time)
        .limit(limite)
    ).all()
    contatori = {"documenti": 0, "classificati": 0, "da_rivedere": 0, "ignorati": 0, "errori": 0}
    catalogo_testo = catalogo.testo_prompt()
    for i in range(0, len(in_attesa), DOCUMENTI_PER_CHIAMATA):
        gruppo = in_attesa[i : i + DOCUMENTI_PER_CHIAMATA]
        contatori["documenti"] += len(gruppo)
        try:
            risultato = classificatore.classifica_documenti(catalogo_testo, _prompt_documenti(account, gruppo))
        except ErroreClassificazione as exc:
            contatori["errori"] += 1
            run.errori = [*run.errori, str(exc)]
            for d in gruppo:
                tentativi = int((d.classificazione or {}).get("tentativi", 0)) + 1
                d.classificazione = {"tentativi": tentativi, "ultimo_errore": str(exc)}
                if not exc.temporaneo or tentativi >= MAX_TENTATIVI:
                    d.stato = StatoMessaggio.ERRORE
                    d.motivo = f"Classificazione fallita: {exc}"[:500]
            session.commit()
            if not exc.temporaneo and "IA disabilitata" in str(exc):
                break
            continue
        per_id = {r.id: r for r in risultato.documenti}
        for d in gruppo:
            r = per_id.get(d.drive_file_id)
            if r is None:
                d.stato = StatoMessaggio.DA_RIVEDERE
                d.motivo = "IA: nessun risultato per questo documento"
                d.processed_at = utcnow()
                contatori["da_rivedere"] += 1
                continue
            collega_documento(session, d, r, catalogo, settings)
            contatori[
                "classificati" if d.stato == StatoMessaggio.CLASSIFICATO else ("ignorati" if d.stato == StatoMessaggio.IGNORATO else "da_rivedere")
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
