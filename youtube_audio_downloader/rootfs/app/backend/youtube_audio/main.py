"""FastAPI application factory and lifecycle."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import create_router
from .config import Settings
from .database import Database
from .errors import AppError
from .events import EventBroker
from .queue import QueueService
from .security import IngressOnlyMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
LOGGER = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or Settings.load()
    runtime_settings.prepare_directories()
    database = Database(str(runtime_settings.database_path))
    events = EventBroker()
    queue = QueueService(runtime_settings, database, events)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        await database.open()
        await queue.start()
        app.state.accepting_requests = True
        LOGGER.info(
            "Starting YouTube Audio Downloader version=%s output=%s quality=%d",
            __version__,
            runtime_settings.resolved_output_directory,
            runtime_settings.mp3_quality,
        )
        try:
            yield
        finally:
            app.state.accepting_requests = False
            await queue.stop()
            await database.close()
            LOGGER.info("YouTube Audio Downloader stopped")

    app = FastAPI(
        title="YouTube Audio Downloader",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = runtime_settings
    app.state.database = database
    app.state.queue = queue
    app.state.events = events
    app.add_middleware(IngressOnlyMiddleware)

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "The request body or parameters are invalid.",
                }
            },
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        LOGGER.exception("Unhandled API error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": {"code": "internal_error", "message": "An unexpected error occurred."}
            },
        )

    app.include_router(create_router(runtime_settings, database, queue, events))
    if runtime_settings.frontend_root.is_dir():
        app.mount(
            "/",
            StaticFiles(directory=runtime_settings.frontend_root, html=True),
            name="frontend",
        )
    return app
