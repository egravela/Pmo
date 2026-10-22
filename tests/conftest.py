"""Configurazione dei test: database SQLite temporaneo, IA disabilitata, login di sviluppo."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="pmo-test-"))
os.environ.update(
    {
        "PMO_DATABASE_URL": f"sqlite:///{_TMP / 'test.sqlite'}",
        "PMO_DATA_DIR": str(_TMP),
        "PMO_DEV_LOGIN": "true",
        "PMO_AI_ENABLED": "false",
        "PMO_SCHEDULER_ENABLED": "false",
        "PMO_SECRET_KEY": "chiave-di-test",
        "PMO_ALLOWED_DOMAINS": "latraccia.it",
        "PMO_INTERNAL_DOMAINS": "latraccia.it",
        "PMO_ADMIN_EMAILS": "admin@latraccia.it",
        "PMO_BASE_URL": "http://testserver",
        "PMO_EXTRACT_ATTACHMENTS": "false",
    }
)
os.environ.pop("ANTHROPIC_API_KEY", None)


@pytest.fixture
def db():
    from pmo.db import models  # noqa: F401
    from pmo.db.base import Base
    from pmo.db.session import get_engine, get_session

    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = get_session()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def settings():
    from pmo.config import get_settings

    return get_settings()
