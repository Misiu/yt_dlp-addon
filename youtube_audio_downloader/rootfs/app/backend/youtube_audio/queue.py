"""Durable single-consumer FIFO queue."""

from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import Settings
from .database import Database
from .errors import AppError
from .events import EventBroker
from .media import CancelledError, MediaPipeline
from .models import ACTIVE_STATES, TERMINAL_STATES, Job, JobState
from .validation import parse_youtube_url

LOGGER = logging.getLogger(__name__)


class QueueService:
    def __init__(self, settings: Settings, database: Database, events: EventBroker) -> None:
        self.settings = settings
        self.database = database
        self.events = events
        self.pipeline = MediaPipeline(settings)
        self.current: Job | None = None
        self.stopping = False
        self._wake = asyncio.Event()
        self._worker: asyncio.Task[None] | None = None
        self._mutation_lock = asyncio.Lock()

    async def start(self) -> None:
        recovered = await self.database.recover_interrupted()
        await self._cleanup_stale_temp()
        self._worker = asyncio.create_task(self._run(), name="download-worker")
        self._wake.set()
        LOGGER.info("Queue started; recovered_jobs=%d", recovered)

    async def stop(self) -> None:
        self.stopping = True
        self._wake.set()
        await self.pipeline.cancel()
        if self._worker is not None:
            try:
                await asyncio.wait_for(self._worker, timeout=15)
            except TimeoutError:
                self._worker.cancel()
                await asyncio.gather(self._worker, return_exceptions=True)
        LOGGER.info("Queue stopped")

    async def add(self, url: str) -> Job:
        return (await self.add_many([url]))[0]

    async def add_many(self, urls: list[str]) -> list[Job]:
        if self.stopping:
            raise AppError("service_stopping", "The app is stopping.", 503)
        parsed = [parse_youtube_url(url) for url in urls]
        video_ids = [video_id for _, video_id in parsed]
        if len(video_ids) != len(set(video_ids)):
            raise AppError(
                "duplicate_job", "The request contains the same video more than once.", 409
            )
        async with self._mutation_lock:
            queued = await self.database.count_by_states([JobState.QUEUED, *ACTIVE_STATES])
            if queued + len(parsed) > self.settings.queue_limit:
                raise AppError("queue_full", "The download queue is full.", 409)
            if await self.database.active_video_ids(video_ids):
                raise AppError("duplicate_job", "This video is already queued or active.", 409)
            jobs = [
                Job(id=str(uuid.uuid4()), url=canonical, video_id=video_id)
                for canonical, video_id in parsed
            ]
            await self.database.save_many(jobs)
        LOGGER.info("Queued %d job(s)", len(jobs))
        await self.events.publish(
            "queue_changed", {"jobs": [job.model_dump(mode="json") for job in jobs]}
        )
        self._wake.set()
        return jobs

    async def redownload(self, job_id: str) -> Job:
        """Queue a fresh copy of a history entry and force destination replacement."""
        if self.stopping:
            raise AppError("service_stopping", "The app is stopping.", 503)
        async with self._mutation_lock:
            source = await self.database.get(job_id)
            if source is None:
                raise AppError("job_not_found", "Job not found.", 404)
            if source.state not in TERMINAL_STATES:
                raise AppError(
                    "job_not_redownloadable", "Only history entries can be downloaded again.", 409
                )
            queued = await self.database.count_by_states([JobState.QUEUED, *ACTIVE_STATES])
            if queued >= self.settings.queue_limit:
                raise AppError("queue_full", "The download queue is full.", 409)
            if await self.database.active_video_exists(source.video_id):
                raise AppError("duplicate_job", "This video is already queued or active.", 409)
            job = Job(
                id=str(uuid.uuid4()),
                url=source.url,
                video_id=source.video_id,
                overwrite_existing=True,
            )
            await self.database.save(job)
        LOGGER.info("Queued redownload id=%s source_id=%s", job.id, job_id)
        await self.events.publish("queue_changed", {"jobs": [job.model_dump(mode="json")]})
        self._wake.set()
        return job

    async def remove_queued(self, job_id: str) -> None:
        async with self._mutation_lock:
            job = await self.database.get(job_id)
            if job is None:
                raise AppError("job_not_found", "Job not found.", 404)
            if job.state != JobState.QUEUED or (self.current and self.current.id == job_id):
                raise AppError("job_not_cancellable", "Only waiting jobs can be removed.", 409)
            await self.database.delete(job_id)
        await self.events.publish("queue_changed", {"removed_id": job_id})

    async def cancel(self, job_id: str) -> None:
        if self.current is None or self.current.id != job_id:
            job = await self.database.get(job_id)
            if job is None:
                raise AppError("job_not_found", "Job not found.", 404)
            raise AppError("job_not_cancellable", "This job is not currently active.", 409)
        await self.pipeline.cancel()

    async def delete_history(self, job_id: str) -> None:
        job = await self.database.get(job_id)
        if job is None:
            raise AppError("job_not_found", "Job not found.", 404)
        if job.state not in TERMINAL_STATES:
            raise AppError("job_not_cancellable", "The job is not a history entry.", 409)
        await self.database.delete(job_id)
        await self.events.publish("history_changed", {"removed_id": job_id})

    async def clear_history(self) -> int:
        deleted = await self.database.clear_history()
        await self.events.publish("history_changed", {"cleared": deleted})
        return deleted

    async def update(self, job: Job) -> None:
        await self.database.save(job)
        await self.events.publish("job_updated", {"job": job.model_dump(mode="json")})

    async def _run(self) -> None:
        while not self.stopping:
            jobs = await self.database.list_by_states([JobState.QUEUED], limit=1)
            if not jobs:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=30)
                except TimeoutError:
                    continue
                continue
            await self._execute(jobs[0])

    async def _execute(self, job: Job) -> None:
        self.current = job
        job.started_at = job.started_at or datetime.now(UTC)
        job.error_code = None
        job.error_message = None
        try:
            await self.pipeline.execute(job, self.update)
            job.state = JobState.COMPLETED
            job.finished_at = datetime.now(UTC)
            await self.database.save(job)
            LOGGER.info("Job completed id=%s output=%s", job.id, job.output_file)
            await self.events.publish("job_completed", {"job": job.model_dump(mode="json")})
        except CancelledError:
            job.state = JobState.CANCELLED
            job.finished_at = datetime.now(UTC)
            job.error_code = "cancelled"
            job.error_message = "The download was cancelled."
            await self.database.save(job)
            LOGGER.info("Job cancelled id=%s", job.id)
            await self.events.publish("job_completed", {"job": job.model_dump(mode="json")})
        except AppError as exc:
            failed_stage = job.state
            job.state = JobState.FAILED
            job.finished_at = datetime.now(UTC)
            job.error_code = exc.code
            job.error_message = exc.message
            await self.database.save(job)
            LOGGER.warning(
                "Job failed id=%s video_id=%s stage=%s code=%s message=%s",
                job.id,
                job.video_id,
                failed_stage.value,
                exc.code,
                exc.message,
                exc_info=LOGGER.isEnabledFor(logging.DEBUG),
            )
            await self.events.publish("job_failed", {"job": job.model_dump(mode="json")})
        except Exception:
            job.state = JobState.FAILED
            job.finished_at = datetime.now(UTC)
            job.error_code = "internal_error"
            job.error_message = "An unexpected error stopped this job."
            await self.database.save(job)
            LOGGER.exception("Unexpected job failure id=%s", job.id)
            await self.events.publish("job_failed", {"job": job.model_dump(mode="json")})
        finally:
            self.current = None
            await self.database.trim_history(self.settings.history_limit)
            await self.events.publish("queue_changed", {})
            await self.events.publish("history_changed", {})

    async def _cleanup_stale_temp(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(hours=24)

        def cleanup(root: Path) -> int:
            removed = 0
            if not root.exists():
                return removed
            for path in root.iterdir():
                try:
                    modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
                    if modified < cutoff:
                        if path.is_dir():
                            shutil.rmtree(path)
                        else:
                            path.unlink()
                        removed += 1
                except OSError:
                    LOGGER.warning("Could not inspect or remove stale temporary path %s", path)
            return removed

        removed = await asyncio.to_thread(cleanup, self.settings.temp_root)
        if removed:
            LOGGER.info("Removed %d stale temporary paths", removed)
