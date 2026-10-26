"""Dati per la guida "Collega Claude" dell'interfaccia: percorsi reali, comandi pronti e strumenti del server MCP.

Tutto è ricavato dall'installazione in uso (il venv che sta eseguendo l'applicazione) e dal server MCP stesso,
così la guida non invecchia quando cambiano gli strumenti.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

import pmo
from pmo.config import Settings, get_settings

NOME_PLUGIN = "pmo-la-traccia"
NOME_MARKETPLACE = "la-traccia"
REPOSITORY = "egravela/Pmo"


def radice_progetto() -> Path:
    """Cartella con alembic.ini (e con .env e il database SQLite): quella dove `pmo mcp` si sposta all'avvio."""
    for candidata in (Path(pmo.__file__).resolve().parents[2], Path.cwd()):
        if (candidata / "alembic.ini").exists():
            return candidata
    return Path.cwd()


def eseguibile_pmo() -> Path:
    """Il comando `pmo` dell'ambiente che sta eseguendo l'applicazione."""
    return Path(sys.executable).resolve().parent / ("pmo.exe" if os.name == "nt" else "pmo")


def descrizione_database(settings: Settings) -> str:
    """Dove sono i dati, senza credenziali."""
    url = make_url(settings.database_url)
    if url.get_backend_name() == "sqlite":
        return f"SQLite locale ({url.database})"
    return f"{url.get_backend_name()} su {url.host or 'host locale'}"


def _prima_frase(descrizione: str) -> str:
    testo = " ".join((descrizione or "").replace("`", "").split())
    return testo.split(". ")[0].rstrip(".") + "."


@lru_cache
def strumenti_mcp() -> tuple[dict[str, Any], ...]:
    """Gli strumenti che il server espone, letti dal server (con la scrittura abilitata): nome, frase e se modificano i dati."""
    from pmo.mcp_server import crea_server

    elenco = asyncio.run(crea_server(scrittura=True).list_tools())
    return tuple(
        {
            "nome": t.name,
            "descrizione": _prima_frase(t.description),
            "scrittura": not (t.annotations and t.annotations.read_only_hint),
        }
        for t in elenco
    )


def contesto_guida(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    radice = radice_progetto()
    exe = eseguibile_pmo()
    plugin_nel_progetto = (radice / ".claude-plugin" / "marketplace.json").exists()
    try:
        strumenti = list(strumenti_mcp())
    except Exception:  # noqa: BLE001 - la guida resta leggibile anche se il server non si carica
        strumenti = []
    return {
        "radice": str(radice),
        "eseguibile": str(exe),
        "eseguibile_presente": exe.exists(),
        "plugin_nel_progetto": plugin_nel_progetto,
        "database": descrizione_database(settings),
        "strumenti": strumenti,
        "comandi": {
            "marketplace": f'claude plugin marketplace add "{radice}"',
            "plugin": f"claude plugin install {NOME_PLUGIN}@{NOME_MARKETPLACE}",
            "plugin_github": f"/plugin install {NOME_PLUGIN} --marketplace {REPOSITORY}",
            "verifica": f"/{NOME_PLUGIN}:collega",
            "ricarica": "/reload-plugins",
            "manuale": f'claude mcp add --scope user pmo -- "{exe}" mcp',
            "manuale_scrittura": f'claude mcp add --scope user pmo -- "{exe}" mcp --scrittura',
            "rimuovi_manuale": "claude mcp remove pmo",
            "prova": f'"{exe}" mcp --help',
            "desktop": json.dumps({"mcpServers": {"pmo": {"command": str(exe), "args": ["mcp"]}}}, indent=2, ensure_ascii=False),
        },
    }
