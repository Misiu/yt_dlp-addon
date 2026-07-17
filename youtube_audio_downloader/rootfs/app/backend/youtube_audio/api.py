"""Versioned REST and event API."""

from __future__ import annotations

import asyncio
import json
import platform
import shutil
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from . import __version__
from .config import Settings
from .database import Database
from .errors import AppError
from .events import EventBroker
from .integration import API_VERSION, IntegrationCredentials
from .models import (
    ACTIVE_STATES,
    TERMINAL_STATES,
    BatchDownloadRequest,
    ClearHistoryRequest,
    DownloadRequest,
    JobState,
    Page,
    RedownloadRequest,
)
from .queue import QueueService


def create_router(
    settings: Settings,
    database: Database,
    queue: QueueService,
    events: EventBroker,
    integration_credentials: IntegrationCredentials,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @router.get("/api/v1/info")
    async def info() -> dict[str, object]:
        return {
            "version": __version__,
            "api_version": API_VERSION,
            "instance_id": integration_credentials.instance_id,
            "yt_dlp_version": _module_version("yt_dlp"),
            "ffmpeg_version": await _binary_version("ffmpeg"),
            "architecture": platform.machine(),
            "output_directory": settings.resolved_output_directory.relative_to(
                settings.media_root
            ).as_posix(),
            "database": "/data/youtube_audio.db",
            "queue_limit": settings.queue_limit,
        }

    @router.post("/api/v1/downloads", status_code=status.HTTP_202_ACCEPTED)
    async def add_download(body: DownloadRequest) -> dict[str, str]:
        job = await queue.add(str(body.url))
        return {"id": job.id, "state": job.state.value}

    @router.post("/api/v1/downloads/batch", status_code=status.HTTP_202_ACCEPTED)
    async def add_downloads(body: BatchDownloadRequest) -> dict[str, object]:
        jobs = await queue.add_many(body.urls)
        return {
            "items": [{"id": job.id, "state": job.state.value} for job in jobs],
            "accepted": len(jobs),
        }

    @router.get("/api/v1/status")
    async def overall_status() -> dict[str, object]:
        queued = await database.count_by_states([JobState.QUEUED])
        current = queue.current
        state = current.state.value if current else ("stopping" if queue.stopping else "idle")
        return {
            "state": state,
            "progress": current.progress if current else 0,
            "queue_length": queued,
            "current": current.model_dump(mode="json") if current else None,
        }

    @router.get("/api/v1/queue")
    async def list_queue() -> dict[str, object]:
        jobs = await database.list_by_states([JobState.QUEUED, *ACTIVE_STATES])
        return {"items": [job.model_dump(mode="json") for job in jobs]}

    @router.get("/api/v1/history", response_model=Page)
    async def history(
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 25,
        state_filter: Annotated[JobState | None, Query(alias="state")] = None,
    ) -> Page:
        states = [state_filter] if state_filter in TERMINAL_STATES else list(TERMINAL_STATES)
        total = await database.count_by_states(states)
        items = await database.list_by_states(
            states, limit=page_size, offset=(page - 1) * page_size, newest_first=True
        )
        return Page(items=items, page=page, page_size=page_size, total=total)

    @router.get("/api/v1/downloads/{job_id}")
    async def download_details(job_id: str) -> object:
        job = await database.get(job_id)
        if job is None:
            raise AppError("job_not_found", "Job not found.", 404)
        return job

    @router.delete("/api/v1/queue/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def remove_queued(job_id: str) -> Response:
        await queue.remove_queued(job_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/api/v1/downloads/{job_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
    async def cancel_download(job_id: str) -> dict[str, str]:
        await queue.cancel(job_id)
        return {"id": job_id, "state": "cancelling"}

    @router.delete("/api/v1/history/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_history(job_id: str) -> Response:
        await queue.delete_history(job_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post(
        "/api/v1/history/{job_id}/redownload",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def redownload(job_id: str, body: RedownloadRequest) -> dict[str, str]:
        if not body.confirm:
            raise AppError("confirmation_required", "Set confirm to true.", 400)
        job = await queue.redownload(job_id)
        return {"id": job.id, "state": job.state.value}

    @router.delete("/api/v1/history")
    async def clear_history(body: ClearHistoryRequest) -> dict[str, int]:
        if not body.confirm:
            raise AppError("confirmation_required", "Set confirm to true.", 400)
        return {"deleted": await queue.clear_history()}

    @router.get("/api/v1/config")
    async def effective_config() -> dict[str, object]:
        return {
            "output_directory": settings.output_directory,
            "mp3_quality": settings.mp3_quality,
            "history_limit": settings.history_limit,
            "overwrite_existing": settings.overwrite_existing,
            "concurrent_downloads": 1,
        }

    @router.get("/api/v1/events")
    async def event_stream(request: Request) -> StreamingResponse:
        async def stream() -> AsyncIterator[str]:
            async with events.subscribe() as subscription:
                yield "retry: 3000\n\n"
                while not await request.is_disconnected():
                    try:
                        event = await asyncio.wait_for(subscription.get(), timeout=20)
                        payload = json.dumps(event.data, separators=(",", ":"), default=str)
                        yield f"event: {event.type}\ndata: {payload}\n\n"
                    except TimeoutError:
                        yield ": heartbeat\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    return router


def _module_version(name: str) -> str:
    try:
        module = __import__(name)
        version = getattr(module, "version", None)
        return str(getattr(version, "__version__", getattr(module, "__version__", "unknown")))
    except ImportError:
        return "unavailable"


async def _binary_version(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        return "unavailable"
    try:
        process = await asyncio.create_subprocess_exec(
            path,
            "-version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await asyncio.wait_for(process.communicate(), timeout=3)
    except (OSError, TimeoutError):
        return "unavailable"
    first_line = output.decode("utf-8", errors="replace").splitlines()
    return first_line[0][:200] if first_line else "unknown"
