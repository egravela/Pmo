"""Client Google Drive: esplorazione delle cartelle monitorate ed estrazione di un estratto testuale."""

from __future__ import annotations

import io
import logging
import re
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from dateutil import parser as dateparser
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from pmo.ingest.text_extract import estrai_testo

log = logging.getLogger(__name__)

FOLDER_MIME = "application/vnd.google-apps.folder"
GOOGLE_EXPORT = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}
FILE_FIELDS = (
    "id,name,mimeType,modifiedTime,createdTime,size,webViewLink,parents,"
    "lastModifyingUser(displayName,emailAddress),trashed"
)
_FOLDER_URL_RE = re.compile(r"folders/([A-Za-z0-9_-]{10,})")


@dataclass
class FileDrive:
    id: str
    nome: str
    mime_type: str
    modified_time: datetime | None
    created_time: datetime | None
    size: int | None
    web_view_link: str | None
    parent_id: str | None
    percorso: str
    ultimo_autore: str

    @property
    def is_folder(self) -> bool:
        return self.mime_type == FOLDER_MIME


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return dateparser.isoparse(value)
    except (ValueError, TypeError):
        return None


def _to_file(raw: dict[str, Any], percorso: str) -> FileDrive:
    autore = raw.get("lastModifyingUser") or {}
    size = raw.get("size")
    return FileDrive(
        id=raw["id"],
        nome=raw.get("name") or "",
        mime_type=raw.get("mimeType") or "",
        modified_time=_parse_dt(raw.get("modifiedTime")),
        created_time=_parse_dt(raw.get("createdTime")),
        size=int(size) if size is not None else None,
        web_view_link=raw.get("webViewLink"),
        parent_id=(raw.get("parents") or [None])[0],
        percorso=percorso,
        ultimo_autore=autore.get("emailAddress") or autore.get("displayName") or "",
    )


def estrai_folder_id(valore: str) -> str:
    """Accetta un ID oppure un URL di cartella Drive."""
    valore = (valore or "").strip()
    match = _FOLDER_URL_RE.search(valore)
    if match:
        return match.group(1)
    return valore.split("?")[0]


class DriveClient:
    def __init__(self, credentials):  # noqa: ANN001
        self.service = build("drive", "v3", credentials=credentials, cache_discovery=False)

    def get_file(self, file_id: str) -> dict[str, Any]:
        return self.service.files().get(fileId=file_id, fields=FILE_FIELDS, supportsAllDrives=True).execute()

    def list_children(self, folder_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        page_token = None
        while True:
            resp = (
                self.service.files()
                .list(
                    q=f"'{folder_id}' in parents and trashed = false",
                    fields=f"nextPageToken, files({FILE_FIELDS})",
                    pageSize=200,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            out.extend(resp.get("files", []) or [])
            page_token = resp.get("nextPageToken")
            if not page_token:
                return out

    def cerca_cartelle(self, testo: str, max_results: int = 20) -> list[dict[str, Any]]:
        testo = testo.replace("'", "\\'")
        resp = (
            self.service.files()
            .list(
                q=f"mimeType = '{FOLDER_MIME}' and name contains '{testo}' and trashed = false",
                fields="files(id,name,parents,webViewLink,modifiedTime)",
                pageSize=max_results,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                orderBy="modifiedTime desc",
            )
            .execute()
        )
        return resp.get("files", []) or []

    def walk(self, folder_id: str, nome_radice: str = "", ricorsivo: bool = True, max_cartelle: int = 3000) -> Iterator[FileDrive]:
        """Visita in ampiezza la cartella e restituisce i file (non le cartelle) con il loro percorso."""
        coda: deque[tuple[str, str]] = deque([(folder_id, nome_radice)])
        visitate: set[str] = set()
        while coda:
            fid, percorso = coda.popleft()
            if fid in visitate or len(visitate) >= max_cartelle:
                continue
            visitate.add(fid)
            try:
                figli = self.list_children(fid)
            except HttpError as exc:
                log.warning("Impossibile leggere la cartella %s (%s): %s", fid, percorso, exc)
                continue
            for raw in figli:
                if raw.get("mimeType") == FOLDER_MIME:
                    if ricorsivo:
                        coda.append((raw["id"], f"{percorso}/{raw.get('name', '')}".strip("/")))
                    continue
                yield _to_file(raw, percorso)

    def estratto_testo(self, file: FileDrive, max_chars: int = 4000, max_bytes: int = 8_000_000) -> str:
        """Estratto testuale del file (export per i formati Google, download per PDF/Office/testo)."""
        try:
            if file.mime_type in GOOGLE_EXPORT:
                data = self.service.files().export(fileId=file.id, mimeType=GOOGLE_EXPORT[file.mime_type]).execute()
                if isinstance(data, bytes):
                    data = data.decode("utf-8", errors="replace")
                return (data or "")[:max_chars]
            if file.size is not None and file.size > max_bytes:
                return ""
            if not _estraibile(file.mime_type, file.nome):
                return ""
            buf = io.BytesIO()
            request = self.service.files().get_media(fileId=file.id, supportsAllDrives=True)
            downloader = MediaIoBaseDownload(buf, request, chunksize=4 * 1024 * 1024)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            return estrai_testo(buf.getvalue(), file.mime_type, file.nome, max_chars)
        except HttpError as exc:
            log.warning("Estratto non disponibile per %s: %s", file.nome, exc)
            return ""
        except Exception as exc:  # noqa: BLE001
            log.warning("Errore estrazione testo da %s: %s", file.nome, exc)
            return ""


def _estraibile(mime: str, nome: str) -> bool:
    nome = nome.lower()
    return (
        mime in {"application/pdf", "text/plain", "text/csv", "text/markdown"}
        or mime.endswith("wordprocessingml.document")
        or nome.endswith((".pdf", ".docx", ".txt", ".md", ".csv"))
    )
