import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_migrazione_crea_tutte_le_tabelle(tmp_path):
    url = f"sqlite:///{tmp_path / 'mig.sqlite'}"
    radice = Path(__file__).resolve().parents[1]
    cfg = Config(str(radice / "alembic.ini"))
    cfg.set_main_option("script_location", str(radice / "alembic"))
    os.environ["ALEMBIC_URL"] = url
    try:
        command.upgrade(cfg, "head")
    finally:
        os.environ.pop("ALEMBIC_URL", None)
    tabelle = set(inspect(create_engine(url)).get_table_names())
    attese = {"users", "accounts", "watched_folders", "clienti", "prodotti", "pratiche", "eventi", "messaggi", "documenti", "regole", "solleciti", "sequenze_codici", "sync_runs", "impostazioni"}
    assert attese <= tabelle
