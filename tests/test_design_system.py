"""L'interfaccia deve restare fedele al design system La Traccia (static/ds/, copia non modificata)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from pmo.services import pratiche as svc
from pmo.services.seed import carica_seed


@pytest.fixture
def client(db):
    from pmo.web.app import create_app

    carica_seed(db)
    with TestClient(create_app(), follow_redirects=False) as c:
        yield c


def _login(client: TestClient) -> None:
    pagina = client.get("/login")
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', pagina.text).group(1)
    assert client.post("/auth/dev", data={"email": "admin@latraccia.it", "csrf_token": csrf, "next": "/"}).status_code == 303


@pytest.mark.parametrize(
    "percorso",
    [
        "/static/ds/tokens/tokens.css",
        "/static/ds/css/traccia.css",
        "/static/ds/css/traccia-icons.css",
        "/static/ds/css/traccia-states.css",
        "/static/ds/css/traccia-time.css",
        "/static/ds/css/traccia-fonts.css",
        "/static/ds/js/tr-select.js",
        "/static/ds/assets/logo-traccia-mark.svg",
        "/static/ds/assets/fonts/archivo-latin-var.woff2",
        "/static/ds/assets/fonts/ibm-plex-mono-latin-400.woff2",
        "/static/ds/assets/fonts/space-grotesk-latin-700.woff2",
        "/static/ds/assets/fonts/OFL-Archivo.txt",
        "/static/pmo.css",
        "/static/pmo.js",
    ],
)
def test_risorse_del_design_system_servite(client, percorso):
    assert client.get(percorso).status_code == 200


def test_i_font_sono_in_locale_non_su_cdn(client):
    pagina = client.get("/login").text
    assert "traccia-fonts.css" in pagina
    assert "fonts.googleapis.com" not in pagina


def test_pagina_di_accesso_ha_la_riga_certificazioni(client):
    pagina = client.get("/login").text
    assert "tr-login" in pagina and "tr-footer__certs" in pagina


def test_dentro_l_applicazione_il_footer_non_ha_le_certificazioni(client):
    _login(client)
    pagina = client.get("/").text
    assert "tr-footer" in pagina and "tr-footer__certs" not in pagina


def test_navigazione_segna_la_pagina_corrente_con_aria_current(client):
    _login(client)
    pagina = client.get("/pratiche").text
    assert re.search(r'href="/pratiche"\s+aria-current="page"', pagina)
    assert not re.search(r'href="/solleciti"\s+aria-current', pagina)


def test_nessuna_classe_dell_interfaccia_precedente(client, db):
    _login(client)
    pratica = svc.crea_pratica(db, "Prova grafica")
    db.commit()
    for url in ("/", "/pratiche", f"/pratiche/{pratica.id}", "/pratiche/nuova", "/solleciti", "/revisione", "/caselle", "/impostazioni"):
        html = client.get(url).text
        for vecchia in ('class="badge', 'class="card', 'class="campo"', 'class="piccolo"', "flash "):
            assert vecchia not in html, f"{url}: resta {vecchia!r}"


def test_i_campi_hanno_l_etichetta_dopo_il_controllo(client):
    """Etichetta flottante: il CSS raggiunge l'etichetta con `+`, quindi il controllo viene prima."""
    _login(client)
    html = client.get("/pratiche/nuova").text
    assert re.search(r'<input class="tr-field__control"[^>]*name="titolo"[^>]*>\s*<label class="tr-field__label"', html)


def test_una_sola_azione_primaria_per_schermata(client, db):
    _login(client)
    pratica = svc.crea_pratica(db, "Prova grafica")
    db.commit()
    for url in ("/pratiche", f"/pratiche/{pratica.id}", "/pratiche/nuova", "/solleciti", "/revisione", "/caselle"):
        assert len(re.findall(r"tr-btn--primary", client.get(url).text)) <= 1, url


def test_i_messaggi_flash_diventano_messaggi_transitori(client):
    _login(client)
    r = client.post("/solleciti/ricalcola", data={"csrf_token": re.search(r'name="csrf_token" value="([^"]+)"', client.get("/solleciti").text).group(1)})
    assert r.status_code == 303
    pagina = client.get("/solleciti").text
    assert 'class="tr-toast-region"' in pagina and "tr-toast tr-toast--" in pagina
