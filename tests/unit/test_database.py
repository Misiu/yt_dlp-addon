from datetime import UTC, datetime
from pathlib import Path

import pytest
from youtube_audio.database import Database
from youtube_audio.models import Job, JobState


@pytest.mark.asyncio
async def test_database_persists_and_recovers_active_job(tmp_path: Path) -> None:
    database = Database(str(tmp_path / "jobs.db"))
    await database.open()
    job = Job(
        id="b7fd1aae-f0f2-49f0-a35f-5e55199aa8ff",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        video_id="dQw4w9WgXcQ",
        state=JobState.DOWNLOADING,
        started_at=datetime.now(UTC),
    )
    await database.save(job)
    assert await database.recover_interrupted() == 1
    recovered = await database.get(job.id)
    assert recovered is not None
    assert recovered.state == JobState.QUEUED
    assert recovered.error_code == "restart_requeued"
    await database.close()


@pytest.mark.asyncio
async def test_history_limit_removes_oldest_records(tmp_path: Path) -> None:
    database = Database(str(tmp_path / "jobs.db"))
    await database.open()
    for index in range(3):
        job = Job(
            id=f"00000000-0000-0000-0000-00000000000{index}",
            url=f"https://www.youtube.com/watch?v=video0{index}",
            video_id=f"video0{index}",
            state=JobState.COMPLETED,
        )
        await database.save(job)
    await database.trim_history(2)
    assert await database.count_by_states([JobState.COMPLETED]) == 2
    await database.close()
