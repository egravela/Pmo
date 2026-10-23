"""Le date lette dal database devono avere il fuso orario anche con SQLite (che non lo conserva)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from pmo.db.models import Account, Documento, WatchedFolder


def test_date_lette_da_sqlite_hanno_fuso(db):
    account = Account(email="prova@latraccia.it")
    db.add(account)
    db.flush()
    cartella = WatchedFolder(account_id=account.id, drive_folder_id="cartella-di-prova")
    cartella.last_sync_at = datetime(2026, 10, 1, 12, 0, tzinfo=timezone(timedelta(hours=2)))
    doc = Documento(account_id=account.id, drive_file_id="file-1", nome="a.pdf")
    doc.modified_time = datetime(2026, 10, 2, 8, 30, tzinfo=UTC)
    db.add_all([cartella, doc])
    db.commit()
    db.expire_all()

    letta = db.get(WatchedFolder, cartella.id)
    assert letta.last_sync_at.tzinfo is not None
    assert letta.last_sync_at == datetime(2026, 10, 1, 10, 0, tzinfo=UTC)  # convertita in UTC

    # il confronto che falliva al secondo giro di sincronizzazione di Drive
    nuova_modifica = datetime(2026, 10, 3, tzinfo=UTC)
    assert nuova_modifica > db.get(Documento, doc.id).modified_time
    assert nuova_modifica > letta.last_sync_at - timedelta(hours=1)
