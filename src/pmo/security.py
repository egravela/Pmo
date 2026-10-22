"""Cifratura dei segreti a riposo (token OAuth) con Fernet."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from pmo.config import get_settings

log = logging.getLogger(__name__)


@lru_cache
def get_fernet() -> Fernet:
    settings = get_settings()
    if settings.encryption_key:
        return Fernet(settings.encryption_key.encode())
    # Chiave derivata dal secret_key: accettabile in sviluppo, in produzione impostare PMO_ENCRYPTION_KEY.
    log.warning("PMO_ENCRYPTION_KEY non impostata: la chiave di cifratura viene derivata da PMO_SECRET_KEY")
    digest = hashlib.sha256(settings.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_json(payload: Any) -> str:
    return get_fernet().encrypt(json.dumps(payload).encode()).decode()


def decrypt_json(token: str) -> Any:
    try:
        return json.loads(get_fernet().decrypt(token.encode()).decode())
    except InvalidToken as exc:
        raise ValueError("Impossibile decifrare il token: chiave di cifratura cambiata?") from exc


def genera_chiave() -> str:
    return Fernet.generate_key().decode()
