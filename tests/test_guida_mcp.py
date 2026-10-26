"""La scheda "Collega Claude" delle Impostazioni: comandi e percorsi reali, strumenti letti dal server MCP."""

from __future__ import annotations

import html as html_lib
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pmo.services.mcp_guida import contesto_guida, eseguibile_pmo, radice_progetto
from pmo.services.seed import carica_seed

STRUMENTI = {
    "stato_sistema", "catalogo", "elenca_pratiche", "dettaglio_pratica", "elenca_solleciti", "coda_revisione",
    "cerca_messaggi", "cerca_documenti", "aggiungi_nota", "cambia_stato_pratica", "conferma_pratica",
    "scarta_pratica", "aggiorna_sollecito",
}  # fmt: skip


@pytest.fixture
def client(db):
    from pmo.web.app import create_app

    carica_seed(db)
    with TestClient(create_app(), follow_redirects=False) as c:
        yield c


def _login(client: TestClient, email: str = "admin@latraccia.it") -> None:
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/login").text).group(1)
    assert client.post("/auth/dev", data={"email": email, "csrf_token": csrf, "next": "/"}).status_code == 303


def test_contesto_con_i_percorsi_di_questa_installazione():
    c = contesto_guida()
    assert c["radice"] == str(radice_progetto()) and (Path(c["radice"]) / "alembic.ini").exists()
    assert c["eseguibile"] == str(eseguibile_pmo())
    assert Path(c["eseguibile"]).parent == Path(sys.executable).resolve().parent
    assert c["plugin_nel_progetto"] is True  # questo repository contiene il plugin
    assert "SQLite" in c["database"] and "postgresql://" not in c["database"]


def test_comandi_pronti_con_il_percorso_reale():
    c = contesto_guida()
    comandi = c["comandi"]
    assert comandi["marketplace"] == f'claude plugin marketplace add "{c["radice"]}"'
    assert comandi["plugin"] == "claude plugin install pmo-la-traccia@la-traccia"
    assert comandi["manuale"] == f'claude mcp add --scope user pmo -- "{c["eseguibile"]}" mcp'
    assert comandi["manuale_scrittura"].endswith(" mcp --scrittura")
    assert comandi["verifica"] == "/pmo-la-traccia:collega"
    import json

    assert json.loads(comandi["desktop"])["mcpServers"]["pmo"] == {"command": c["eseguibile"], "args": ["mcp"]}


def test_strumenti_letti_dal_server_con_il_tipo():
    strumenti = {s["nome"]: s for s in contesto_guida()["strumenti"]}
    assert set(strumenti) == STRUMENTI
    assert strumenti["elenca_pratiche"]["scrittura"] is False
    assert strumenti["conferma_pratica"]["scrittura"] is True
    for s in strumenti.values():
        d = s["descrizione"]
        assert d.endswith(".") and "`" not in d
        assert d.count("(") == d.count(")") and d.count('"') % 2 == 0, f"{s['nome']}: frase troncata a metà: {d!r}"
        assert not re.search(r"\b(es|ecc|cfr)\.$", d), f"{s['nome']}: la frase finisce su un'abbreviazione: {d!r}"


def test_scheda_nella_pagina_delle_impostazioni(client):
    _login(client)
    pagina = client.get("/impostazioni?scheda=claude")
    assert pagina.status_code == 200
    testo = html_lib.unescape(pagina.text)
    c = contesto_guida()
    assert re.search(r'href="/impostazioni\?scheda=claude"\s+aria-current="page"', pagina.text)
    for atteso in (c["comandi"]["marketplace"], c["comandi"]["plugin"], c["comandi"]["manuale"], c["eseguibile"], "/reload-plugins"):
        assert atteso in testo, atteso
    for nome in STRUMENTI:
        assert nome in testo, nome
    # ogni comando ha il pulsante di copia e il suo messaggio
    assert testo.count("data-copia=") >= 6 and "data-copia-messaggio=" in testo
    assert "Trovato" in testo or "Non trovato" in testo
    assert "tr-status--warning\">Scrittura" in testo


def test_scheda_rispetta_il_design_system(client):
    _login(client)
    html = client.get("/impostazioni?scheda=claude").text
    assert len(re.findall(r"tr-btn--primary", html)) <= 1
    for vecchia in ('class="badge', 'class="card', 'class="campo"', 'class="piccolo"'):
        assert vecchia not in html
    for titolo in re.findall(r'<h2 class="tr-card__title"[^>]*>(.*?)</h2>', html):
        assert "<em>" in titolo, titolo


def test_scheda_solo_per_gli_amministratori(client):
    _login(client, "membro@latraccia.it")
    assert client.get("/impostazioni?scheda=claude").status_code == 403


def test_le_altre_schede_non_calcolano_la_guida(client):
    _login(client)
    assert "pmo-passi" not in client.get("/impostazioni?scheda=regole").text
