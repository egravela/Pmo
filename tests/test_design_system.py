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


def test_parola_chiave_solo_nei_titoli_scritti_non_in_quelli_presi_dai_dati(client, db):
    """I titoli scritti dall'app hanno la parola chiave in <em>; il titolo di una pratica (un dato) no."""
    _login(client)
    pratica = svc.crea_pratica(db, "Banca degli Occhi")
    db.commit()
    html = client.get(f"/pratiche/{pratica.id}").text
    for titolo in re.findall(r'<h2 class="tr-card__title"[^>]*>(.*?)</h2>', html):
        assert "<em>" in titolo, titolo
    assert re.search(r'<h1 class="pmo-titolo">Banca degli Occhi</h1>', html)
    elenco = client.get("/pratiche").text
    assert '<h2 class="tr-card__title">Banca degli Occhi</h2>' in elenco


def test_testata_di_sezione_con_tratto_d_accento(client):
    _login(client)
    html = client.get("/").text
    assert 'class="pmo-sechead"' in html and "tr-accent-dash" in html


def test_la_sagoma_del_logo_solo_sulla_pagina_di_accesso(client):
    assert "logo-traccia-outline.svg" in client.get("/login").text
    _login(client)
    assert "logo-traccia-outline.svg" not in client.get("/pratiche").text


def test_nessun_pannello_colorato_dietro_ai_contenuti(client, db):
    _login(client)
    pratica = svc.crea_pratica(db, "Prova", stato_verifica="proposto")
    db.commit()
    assert "tr-notice--tint" not in client.get(f"/pratiche/{pratica.id}").text


def test_menu_laterale_con_la_voce_corrente(client):
    _login(client)
    html = client.get("/solleciti").text
    assert 'class="pmo-side"' in html
    assert re.search(r'class="pmo-side__voce" href="/solleciti"\s+aria-current="page"', html)
    assert not re.search(r'href="/pratiche"\s+aria-current', html)
    # il menu non e' piu' una fila di tabs
    assert 'class="tr-tabs pmo-nav"' not in html


def test_login_la_zona_dei_messaggi_resta_fuori_dal_contenitore(client):
    html = client.get("/login").text
    assert '<body class="tr-page">' in html
    assert html.index('class="tr-login tr-watermark-host"') < html.index('class="tr-toast-region"')
    assert "PMO_GOOGLE_CLIENT_ID" not in html


def test_paginazione_dell_elenco_pratiche(client, db):
    _login(client)
    for i in range(30):
        svc.crea_pratica(db, f"Pratica di prova {i:02d}")
    db.commit()
    prima = client.get("/pratiche").text
    assert prima.count('class="tr-card tr-card--action pmo-scheda"') == 24
    assert 'class="pmo-pagine"' in prima and "1–24 di 30" in prima
    assert re.search(r'href="/pratiche\?pagina=2"[^>]*rel="next"|rel="next"[^>]*href="/pratiche\?pagina=2"', prima)
    seconda = client.get("/pratiche?pagina=2").text
    assert seconda.count('class="tr-card tr-card--action pmo-scheda"') == 6
    assert re.search(r'aria-current="page" aria-label="Pagina 2"', seconda)
    # una pagina oltre l'ultima mostra l'ultima, non un elenco vuoto
    assert client.get("/pratiche?pagina=99").text.count("pmo-scheda") >= 6


def test_paginazione_conserva_i_filtri(client, db):
    _login(client)
    for i in range(30):
        svc.crea_pratica(db, f"Ordine {i:02d}")
    db.commit()
    html = client.get("/pratiche?q=Ordine").text
    assert "q=Ordine&amp;pagina=2" in html


def test_dettaglio_con_viste_e_barra_in_fondo(client, db):
    _login(client)
    pratica = svc.crea_pratica(db, "Prova viste")
    db.commit()
    html = client.get(f"/pratiche/{pratica.id}").text
    assert 'class="tr-tabs tr-tabs--bottom pmo-viste-barra" role="tablist"' in html
    for vista in ("cronologia", "messaggi", "documenti", "solleciti", "scheda"):
        assert f'id="vista-{vista}" role="tabpanel" aria-labelledby="tab-{vista}"' in html
        assert f'id="tab-{vista}" aria-controls="vista-{vista}"' in html
    assert html.count('aria-selected="true"') == 1


def test_tappe_della_pratica_in_riga(client, db):
    _login(client)
    pratica = svc.crea_pratica(db, "Prova tappe", stato="ordine")
    db.commit()
    html = client.get(f"/pratiche/{pratica.id}").text
    assert "tr-timeline tr-timeline--row" in html
    assert html.count('aria-current="step"') == 1


def test_ogni_pagina_si_apre_su_un_pannello_bianco(client, db):
    """La testata di ogni pagina sta sul piano 1 (.tr-panel), non sul fondo della pagina."""
    _login(client)
    pratica = svc.crea_pratica(db, "Prova pannelli")
    db.commit()
    for url in ("/", "/pratiche", f"/pratiche/{pratica.id}", "/pratiche/nuova", "/solleciti", "/revisione", "/caselle", "/impostazioni"):
        html = client.get(url).text
        assert re.search(r'<main[^>]*>\s*<div class="tr-panel">', html), url
    # le code di revisione chiudono il pannello di testa
    html = client.get("/revisione").text
    assert re.search(r'<nav class="tr-tabs pmo-sottonav"[^>]*>(?:(?!</div>).)*</nav>\s*</div>', html, re.S)


def test_contatori_delle_esecuzioni_in_frase():
    from pmo.web.deps import f_contatori, f_esecuzione

    testo = f_contatori({"messaggi": 1000, "da_rivedere": 542, "token": {"chiamate": 515}, "anteprima": True})
    assert testo == "messaggi 1.000 · da rivedere 542 · token chiamate 515 · anteprima sì"
    assert f_contatori(None) == ""
    assert f_esecuzione("classify_drive") == "Classificazione documenti"


def test_opzioni_scritte_in_frase(client):
    _login(client)
    html = client.get("/solleciti").text
    assert ">In carico</option>" in html and ">in_carico</option>" not in html
