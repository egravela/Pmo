"""Configurazione dell'applicazione (variabili d'ambiente con prefisso PMO_)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ListaCSV = Annotated[list[str], NoDecode]  # liste accettate come "a,b,c" nelle variabili d'ambiente

GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_SEND = "https://www.googleapis.com/auth/gmail.send"
DRIVE_READONLY = "https://www.googleapis.com/auth/drive.readonly"
OPENID_SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PMO_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Applicazione ---------------------------------------------------------------------------
    app_name: str = "PMO La Traccia"
    base_url: str = "http://localhost:8000"
    secret_key: str = "cambiami-in-produzione"
    encryption_key: str | None = None  # chiave Fernet (base64, 32 byte) per cifrare i token Google
    timezone: str = "Europe/Rome"
    data_dir: Path = Path("data")
    dev_login: bool = False  # consente il login senza Google (solo sviluppo)
    log_level: str = "INFO"

    # --- Database -------------------------------------------------------------------------------
    database_url: str = "sqlite:///data/pmo.sqlite"

    # --- Google OAuth ---------------------------------------------------------------------------
    google_client_id: str | None = None
    google_client_secret: str | None = None
    allowed_domains: ListaCSV = Field(default_factory=lambda: ["latraccia.it"])
    admin_emails: ListaCSV = Field(default_factory=list)
    gmail_send_scope: bool = False  # richiede anche lo scope gmail.send (per inviare il digest dalla casella)

    # --- Sincronizzazione -----------------------------------------------------------------------
    sync_window_days: int = 120  # finestra iniziale di importazione della posta
    sync_interval_minutes: int = 30
    max_messages_per_run: int = 300
    extract_attachments: bool = True
    attachment_max_mb: int = 5
    body_max_chars: int = 6000
    internal_domains: ListaCSV = Field(default_factory=lambda: ["latraccia.it"])

    # --- Intelligenza artificiale ---------------------------------------------------------------
    ai_enabled: bool = True
    anthropic_api_key: str | None = None  # in alternativa usa ANTHROPIC_API_KEY
    claude_model: str = "claude-opus-5-5"
    claude_effort: str = "low"
    claude_max_tokens: int = 8000
    claude_fallbacks: bool = True
    link_confidence_threshold: float = 0.8  # sotto questa soglia il collegamento va verificato
    event_confidence_threshold: float = 0.7  # sotto questa soglia l'evento resta "proposto"

    # --- Scheduler e digest ---------------------------------------------------------------------
    scheduler_enabled: bool = False
    digest_enabled: bool = True
    digest_hour: int = 8
    digest_minute: int = 0
    digest_recipients: ListaCSV = Field(default_factory=list)  # se vuoto: tutti gli utenti attivi

    # --- SMTP (alternativa all'invio via Gmail) -------------------------------------------------
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_starttls: bool = True

    @field_validator("allowed_domains", "admin_emails", "internal_domains", "digest_recipients", mode="before")
    @classmethod
    def _split_csv(cls, value):  # noqa: ANN001
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("["):
                import json

                return [str(v).strip().lower() for v in json.loads(value)]
            return [v.strip().lower() for v in value.split(",") if v.strip()]
        return value

    @property
    def gmail_scopes(self) -> list[str]:
        scopes = [GMAIL_READONLY, DRIVE_READONLY]
        if self.gmail_send_scope:
            scopes.append(GMAIL_SEND)
        return scopes

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
