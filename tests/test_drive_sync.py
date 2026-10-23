"""Sincronizzazione Drive: il secondo giro (incrementale) non deve confrontare date naive con date aware."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pmo.connectors.drive import FileDrive
from pmo.db.models import Account, Documento, WatchedFolder
from pmo.ingest import drive_sync


class _ClienteFinto:
    def __init__(self, files):
        self.files = files

    def walk(self, folder_id, nome="", ricorsivo=True, max_cartelle=3000):  # noqa: ANN001, ARG002
        yield from self.files

    def estratto_testo(self, file, max_chars=4000, max_bytes=8_000_000):  # noqa: ANN001, ARG002
        return "testo"


def _file(modificato):
    return FileDrive(id="f1", nome="Offerta.pdf", mime_type="application/pdf", modified_time=modificato, created_time=modificato,
                     size=10, web_view_link="https://drive.google.com/", parent_id="p", percorso="2026/Cliente", ultimo_autore="a@x.it")


def test_secondo_giro_con_documento_gia_presente(db, monkeypatch):
    acc = Account(email="a@latraccia.it", token_cifrato="x")
    db.add(acc)
    db.flush()
    cartella = WatchedFolder(account_id=acc.id, drive_folder_id="cart", nome="2026", ricorsivo=True)
    db.add(cartella)
    db.commit()

    t0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
    cliente = _ClienteFinto([_file(t0)])
    monkeypatch.setattr(drive_sync, "credentials_per_account", lambda *a, **k: object())
    monkeypatch.setattr(drive_sync, "DriveClient", lambda creds: cliente)

    run1 = drive_sync.sincronizza_drive(db, acc)
    assert run1.stato == "ok", run1.errori

    # il file viene modificato dopo la prima scansione: il secondo giro deve rilevarlo
    cliente.files = [_file(datetime.now(UTC) + timedelta(minutes=5))]
    db.expire_all()
    run2 = drive_sync.sincronizza_drive(db, acc)
    assert run2.stato == "ok", run2.errori
    assert run2.contatori["nuovi_o_modificati"] == 1
    assert db.query(Documento).count() == 1
