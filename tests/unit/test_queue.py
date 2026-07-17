from pathlib import Path

import pytest
from youtube_audio.config import Settings
from youtube_audio.database import Database
from youtube_audio.events import EventBroker
from youtube_audio.models import Job, JobState
from youtube_audio.queue import QueueService


class CompletingPipeline:
    async def execute(self, job: Job, update: object) -> Job:
        job.title = "Finished track"
        job.output_file = "youtube_audio/Finished track.mp3"
        job.file_size = 1_024
        job.progress = 100
        return job

    async def cancel(self) -> None:
        return None


async def make_queue(tmp_path: Path) -> tuple[QueueService, Database, EventBroker]:
    settings = Settings(
        data_root=tmp_path / "data",
        media_root=tmp_path / "media",
        frontend_root=tmp_path / "frontend",
    )
    settings.prepare_directories()
    database = Database(str(settings.database_path))
    await database.open()
    events = EventBroker()
    queue = QueueService(settings, database, events)
    queue.pipeline = CompletingPipeline()  # type: ignore[assignment]
    return queue, database, events


@pytest.mark.asyncio
async def test_successful_last_download_emits_file_then_queue_completion(
    tmp_path: Path,
) -> None:
    queue, database, events = await make_queue(tmp_path)
    job = Job(
        id="job-1",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        video_id="dQw4w9WgXcQ",
    )
    await database.save(job)

    try:
        async with events.subscribe() as subscription:
            await queue._execute(job)
            emitted = []
            while not subscription.empty():
                emitted.append(subscription.get_nowait())
    finally:
        await database.close()

    event_types = [event.type for event in emitted]
    assert event_types == [
        "job_completed",
        "download_completed",
        "queue_changed",
        "history_changed",
        "queue_completed",
    ]
    download = next(event for event in emitted if event.type == "download_completed")
    assert download.data["job"]["output_file"] == "youtube_audio/Finished track.mp3"
    completed = next(event for event in emitted if event.type == "queue_completed")
    assert completed.data["queue_length"] == 0
    assert completed.data["last_job"]["id"] == "job-1"


@pytest.mark.asyncio
async def test_queue_completion_waits_for_the_last_queued_job(tmp_path: Path) -> None:
    queue, database, events = await make_queue(tmp_path)
    current = Job(
        id="job-1",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        video_id="dQw4w9WgXcQ",
    )
    waiting = Job(
        id="job-2",
        url="https://www.youtube.com/watch?v=9bZkp7q19f0",
        video_id="9bZkp7q19f0",
        state=JobState.QUEUED,
    )
    await database.save_many([current, waiting])

    try:
        async with events.subscribe() as subscription:
            await queue._execute(current)
            event_types = []
            while not subscription.empty():
                event_types.append(subscription.get_nowait().type)
    finally:
        await database.close()

    assert "download_completed" in event_types
    assert "queue_completed" not in event_types
