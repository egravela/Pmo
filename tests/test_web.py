"""Smoke test dell'interfaccia web con login di sviluppo e database SQLite."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from pmo.db.models import Account, Messaggio, StatoMessaggio, StatoPratica
from pmo.services import pratiche as svc
from pmo.services.seed import carica_seed


@pytest.fixture
def client(db):
    from pmo.web.app import create_app

    carica_seed(db)
    app = create_app()
    with TestClient(app, follow_redirects=False) as c:
        yield c


def _login(client: TestClient, email: str = "admin@latraccia.it") -> str:
    pagina = client.get("/login")
    assert pagina.status_code == 200
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', pagina.text).group(1)
    risposta = client.post("/auth/dev", data={"email": email, "csrf_token": csrf, "next": "/"})
    assert risposta.status_code == 303 and risposta.headers["location"] == "/"
    return csrf


def test_redirect_a_login_se_non_autenticato(client):
    r = client.get("/pratiche")
    assert r.status_code == 303 and r.headers["location"].startswith("/login")


def test_dominio_non_consentito(client):
    pagina = client.get("/login")
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', pagina.text).group(1)
    r = client.post("/auth/dev", data={"email": "x@gmail.com", "csrf_token": csrf, "next": "/"})
    assert r.headers["location"] == "/login"
    assert client.get("/").status_code == 303


def test_percorso_completo(client, db):
    csrf = _login(client)
    assert client.get("/").status_code == 200

    # crea una pratica dal form
    r = client.post(
        "/pratiche",
        data={"csrf_token": csrf, "titolo": "Banca degli Occhi – canoni", "stato": "offerta", "importo_offerta": "12.500,00", "data_scadenza": "2027-01-31", "priorita": "alta", "descrizione": "", "cliente_id": "", "prodotto_id": "", "responsabile_id": "", "importo_ordine": ""},
    )
    assert r.status_code == 303
    url = r.headers["location"]
    pratica_id = int(url.rsplit("/", 1)[1])
    dettaglio = client.get(url)
    assert dettaglio.status_code == 200 and "PMO-" in dettaglio.text and "Copia oggetto mail" in dettaglio.text

    # evento manuale: ordine ricevuto → la pratica avanza
    r = client.post(f"/pratiche/{pratica_id}/eventi", data={"csrf_token": csrf, "tipo": "ordine_ricevuto", "titolo": "Ordine n. 12", "importo": "12.000", "data_evento": "2026-10-01", "descrizione": "", "scadenza": ""})
    assert r.status_code == 303
    assert "Ordine" in client.get(url).text
    elenco = client.get("/pratiche?stato=ordine")
    assert elenco.status_code == 200 and "Banca degli Occhi" in elenco.text

    # cambio stato, solleciti, revisione, caselle, impostazioni
    assert client.post(f"/pratiche/{pratica_id}/stato", data={"csrf_token": csrf, "stato": "consegna", "motivo": "rilasciato"}).status_code == 303
    assert client.post("/solleciti/ricalcola", data={"csrf_token": csrf}).status_code == 303
    assert client.get("/solleciti").status_code == 200
    assert client.get("/solleciti?stato=&gravita=critico").status_code == 200
    for scheda in ("pratiche", "messaggi", "documenti", "errori"):
        assert client.get(f"/revisione?scheda={scheda}").status_code == 200
    assert client.get("/caselle").status_code == 200
    for scheda in ("regole", "filtri", "digest", "clienti", "prodotti", "utenti"):
        assert client.get(f"/impostazioni?scheda={scheda}").status_code == 200
    assert client.get("/pratiche/nuova").status_code == 200
    assert client.get("/healthz").status_code == 200


def test_revisione_messaggio_e_collegamento_manuale(client, db):
    csrf = _login(client)
    acc = Account(email="egravela@latraccia.it", token_cifrato="x")
    db.add(acc)
    db.flush()
    pratica = svc.crea_pratica(db, "LURTO Umberto I", stato=StatoPratica.OFFERTA)
    m = Messaggio(account_id=acc.id, gmail_message_id="g1", gmail_thread_id="t1", subject="Ordine LURTO", from_email="x@policlinicoumberto1.it", to_emails=[], cc_emails=[], data=datetime.now(UTC) - timedelta(days=1), body_text="ordine", stato=StatoMessaggio.DA_RIVEDERE, motivo="IA: pratica non identificata")
    db.add(m)
    db.commit()
    pagina = client.get("/revisione?scheda=messaggi")
    assert re.search(r"Ordine\s*(<em>)?LURTO", pagina.text)  # la parola chiave del titolo sta in <em>
    r = client.post(f"/messaggi/{m.id}/collega", data={"csrf_token": csrf, "codice": pratica.codice, "ritorno": "/revisione?scheda=messaggi"})
    assert r.status_code == 303
    db.expire_all()
    db.refresh(m)
    assert m.pratica_id == pratica.id and m.stato == StatoMessaggio.CLASSIFICATO and m.link_origine == "manuale"
    assert pratica.codice in client.get(f"/pratiche/{pratica.id}").text


def test_csrf_obbligatorio(client):
    _login(client)
    r = client.post("/pratiche", data={"titolo": "senza token"})
    assert r.status_code == 400


def test_impostazioni_riservate_agli_admin(client, db):
    _login(client, "membro@latraccia.it")
    assert client.get("/impostazioni").status_code == 403
