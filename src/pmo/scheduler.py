"""Scheduler in-process (APScheduler): sincronizzazione periodica e digest giornaliero."""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from pmo.config import Settings, get_settings
from pmo.db.session import session_scope
from pmo.services.digest import invia_digest
from pmo.services.sync import sincronizza_tutto

log = logging.getLogger(__name__)


def _job_sync(settings: Settings) -> None:
    log.info("Scheduler: avvio sincronizzazione")
    esiti = sincronizza_tutto(settings)
    log.info("Scheduler: sincronizzazione completata: %s", esiti)


def _job_digest(settings: Settings) -> None:
    if not settings.digest_enabled:
        return
    with session_scope() as session:
        esito = invia_digest(session, settings)
    log.info("Scheduler: digest %s", "inviato" if esito.get("inviato") else f"non inviato ({esito.get('errore')})")


def crea_scheduler(settings: Settings | None = None) -> BackgroundScheduler:
    settings = settings or get_settings()
    scheduler = BackgroundScheduler(timezone=settings.timezone)
    scheduler.add_job(
        _job_sync,
        IntervalTrigger(minutes=max(5, settings.sync_interval_minutes)),
        args=[settings],
        id="sync",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
    )
    scheduler.add_job(
        _job_digest,
        CronTrigger(hour=settings.digest_hour, minute=settings.digest_minute, timezone=settings.timezone),
        args=[settings],
        id="digest",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    return scheduler
