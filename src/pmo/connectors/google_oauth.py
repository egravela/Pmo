"""OAuth Google: login degli utenti e collegamento delle caselle (Gmail + Drive in sola lettura).

Due flussi distinti con lo stesso client OAuth:
- login: scope OpenID (identità) per entrare nell'applicazione;
- collegamento casella: scope Gmail/Drive con access_type=offline per ottenere il refresh token,
  che viene salvato cifrato sull'Account.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token as google_id_token
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from pmo.config import OPENID_SCOPES, Settings, get_settings
from pmo.db.models import Account
from pmo.security import decrypt_json, encrypt_json

log = logging.getLogger(__name__)

# Google può restituire un insieme di scope diverso da quello richiesto (l'utente può deselezionarne
# alcuni): senza questa variabile oauthlib solleva un errore invece di proseguire.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"


class GoogleNonConfigurato(RuntimeError):
    pass


def _client_config(settings: Settings, redirect_uri: str) -> dict[str, Any]:
    if not settings.google_configured:
        raise GoogleNonConfigurato("Impostare PMO_GOOGLE_CLIENT_ID e PMO_GOOGLE_CLIENT_SECRET")
    if redirect_uri.startswith("http://"):
        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": AUTH_URI,
            "token_uri": TOKEN_URI,
            "redirect_uris": [redirect_uri],
        }
    }


def redirect_uri_login(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return settings.base_url.rstrip("/") + "/auth/callback"


def redirect_uri_account(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return settings.base_url.rstrip("/") + "/caselle/callback"


def build_flow(scopes: list[str], redirect_uri: str, state: str | None = None, settings: Settings | None = None) -> Flow:
    settings = settings or get_settings()
    flow = Flow.from_client_config(_client_config(settings, redirect_uri), scopes=scopes, state=state)
    flow.redirect_uri = redirect_uri
    return flow


def url_login(settings: Settings | None = None) -> tuple[str, str]:
    """URL di autorizzazione per il login (identità soltanto)."""
    flow = build_flow(OPENID_SCOPES, redirect_uri_login(settings), settings=settings)
    url, state = flow.authorization_url(prompt="select_account", include_granted_scopes="false")
    return url, state


def url_collega_casella(settings: Settings | None = None, login_hint: str | None = None) -> tuple[str, str]:
    """URL di autorizzazione per collegare una casella (refresh token offline)."""
    settings = settings or get_settings()
    scopes = OPENID_SCOPES + settings.gmail_scopes
    flow = build_flow(scopes, redirect_uri_account(settings), settings=settings)
    extra: dict[str, Any] = {"access_type": "offline", "prompt": "consent", "include_granted_scopes": "false"}
    if login_hint:
        extra["login_hint"] = login_hint
    url, state = flow.authorization_url(**extra)
    return url, state


def completa_login(authorization_response: str, state: str, settings: Settings | None = None) -> dict[str, Any]:
    """Completa il login e restituisce le informazioni verificate dell'utente (email, nome, sub, hd)."""
    settings = settings or get_settings()
    flow = build_flow(OPENID_SCOPES, redirect_uri_login(settings), state=state, settings=settings)
    flow.fetch_token(authorization_response=authorization_response)
    creds = flow.credentials
    return _claims_da_id_token(creds, settings)


def completa_collegamento(
    authorization_response: str, state: str, settings: Settings | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Completa il collegamento di una casella: restituisce (claims utente, token da salvare)."""
    settings = settings or get_settings()
    scopes = OPENID_SCOPES + settings.gmail_scopes
    flow = build_flow(scopes, redirect_uri_account(settings), state=state, settings=settings)
    flow.fetch_token(authorization_response=authorization_response)
    creds = flow.credentials
    claims = _claims_da_id_token(creds, settings)
    return claims, credentials_to_dict(creds)


def _claims_da_id_token(creds: Credentials, settings: Settings) -> dict[str, Any]:
    raw = getattr(creds, "id_token", None)
    if not raw:
        raise RuntimeError("Google non ha restituito un id_token: verificare gli scope OpenID")
    claims = google_id_token.verify_oauth2_token(raw, GoogleRequest(), settings.google_client_id)
    email = (claims.get("email") or "").lower()
    if not email or not claims.get("email_verified", False):
        raise RuntimeError("Indirizzo email non verificato da Google")
    return {
        "email": email,
        "nome": claims.get("name") or email,
        "sub": claims.get("sub"),
        "hd": claims.get("hd"),
        "picture": claims.get("picture"),
    }


def dominio_consentito(email: str, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    if not settings.allowed_domains:
        return True
    dominio = email.rsplit("@", 1)[-1].lower()
    return dominio in {d.lower() for d in settings.allowed_domains}


def credentials_to_dict(creds: Credentials) -> dict[str, Any]:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri or TOKEN_URI,
        "scopes": list(creds.scopes or []),
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }


def salva_token(account: Account, token: dict[str, Any]) -> None:
    """Salva i token sull'account mantenendo un refresh token già noto se Google non lo rimanda."""
    precedente: dict[str, Any] = {}
    if account.token_cifrato:
        try:
            precedente = decrypt_json(account.token_cifrato)
        except ValueError:
            precedente = {}
    if not token.get("refresh_token") and precedente.get("refresh_token"):
        token["refresh_token"] = precedente["refresh_token"]
    account.token_cifrato = encrypt_json(token)
    account.scopes = token.get("scopes") or []


def credentials_per_account(account: Account, settings: Settings | None = None) -> Credentials:
    """Ricostruisce le credenziali Google dell'account, rinnovando l'access token se scaduto."""
    settings = settings or get_settings()
    if not account.token_cifrato:
        raise RuntimeError(f"La casella {account.email} non è collegata")
    data = decrypt_json(account.token_cifrato)
    expiry = None
    if data.get("expiry"):
        expiry = datetime.fromisoformat(data["expiry"])
        if expiry.tzinfo is not None:
            expiry = expiry.astimezone(UTC).replace(tzinfo=None)  # google-auth usa datetime naive in UTC
    creds = Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri") or TOKEN_URI,
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=data.get("scopes") or settings.gmail_scopes,
        expiry=expiry,
    )
    if not creds.valid:
        if not creds.refresh_token:
            raise RuntimeError(f"Token scaduto e nessun refresh token per {account.email}: ricollegare la casella")
        creds.refresh(GoogleRequest())
        salva_token(account, credentials_to_dict(creds))
    return creds


def scope_presente(account: Account, scope: str) -> bool:
    return scope in (account.scopes or [])
