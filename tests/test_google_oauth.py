"""Il flusso OAuth è in due richieste con due oggetti Flow diversi: non deve richiedere un verifier PKCE."""

from __future__ import annotations

from pmo.config import Settings
from pmo.connectors.google_oauth import url_collega_casella, url_login


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        google_client_id="id-di-prova.apps.googleusercontent.com",
        google_client_secret="segreto-di-prova",
        base_url="http://localhost:8001",
    )


def test_url_login_senza_pkce():
    url, state = url_login(_settings())
    assert state
    assert "code_challenge" not in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8001%2Fauth%2Fcallback" in url


def test_url_collegamento_casella_senza_pkce_e_con_refresh_token():
    url, _ = url_collega_casella(_settings())
    assert "code_challenge" not in url
    assert "access_type=offline" in url
    assert "gmail.readonly" in url
