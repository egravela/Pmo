"""Applicazione FastAPI: interfaccia web del PMO."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from pmo.config import get_settings
from pmo.web.deps import STATIC_DIR, NonAutenticato
from pmo.web.routes import auth, caselle, dashboard, impostazioni, pratiche, revisione, solleciti

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN202
        scheduler = None
        if settings.scheduler_enabled:
            from pmo.scheduler import crea_scheduler

            scheduler = crea_scheduler(settings)
            scheduler.start()
            log.info("Scheduler avviato (sync ogni %s minuti, digest alle %02d:%02d)", settings.sync_interval_minutes, settings.digest_hour, settings.digest_minute)
        try:
            yield
        finally:
            if scheduler is not None:
                scheduler.shutdown(wait=False)

    app = FastAPI(title=settings.app_name, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        same_site="lax",
        https_only=settings.base_url.startswith("https://"),
        max_age=14 * 24 * 3600,
    )
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.exception_handler(NonAutenticato)
    async def _non_autenticato(request: Request, exc: NonAutenticato):  # noqa: ANN202
        destinazione = request.url.path
        if request.url.query:
            destinazione += "?" + request.url.query
        return RedirectResponse(f"/login?next={quote(destinazione)}", status_code=303)

    for router in (auth.router, dashboard.router, pratiche.router, solleciti.router, revisione.router, caselle.router, impostazioni.router):
        app.include_router(router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict:
        return {"ok": True}

    return app
