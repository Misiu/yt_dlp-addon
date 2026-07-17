import asyncio
import errno
import io
import os
from pathlib import Path

import pytest
from PIL import Image
from youtube_audio.errors import AppError
from youtube_audio.media import (
    MediaPipeline,
    _atomic_publish,
    _normalize_cover,
    _read_stream_limited,
)
from youtube_audio.models import Job


def test_cover_is_bounded_jpeg() -> None:
    source = io.BytesIO()
    Image.new("RGBA", (2000, 1000), (3, 169, 244, 128)).save(source, "PNG")
    result = _normalize_cover(source.getvalue())
    assert len(result) <= 2_000_000
    with Image.open(io.BytesIO(result)) as image:
        assert image.format == "JPEG"
        assert image.width <= 1600
        assert image.height <= 1600


def test_atomic_publish_stages_file_on_destination_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_directory = tmp_path / "data"
    destination_directory = tmp_path / "media"
    source_directory.mkdir()
    destination_directory.mkdir()
    source = source_directory / "encoded.mp3"
    destination = destination_directory / "finished.mp3"
    source.write_bytes(b"complete mp3")
    real_replace = os.replace

    def reject_cross_device_replace(
        source_path: os.PathLike[str], target_path: os.PathLike[str]
    ) -> None:
        source_parent = Path(source_path).parent.resolve()
        target_parent = Path(target_path).parent.resolve()
        if source_parent != target_parent:
            raise OSError(errno.EXDEV, "Cross-device link")
        real_replace(source_path, target_path)

    monkeypatch.setattr(os, "replace", reject_cross_device_replace)

    _atomic_publish(source, destination)

    assert destination.read_bytes() == b"complete mp3"
    assert source.read_bytes() == b"complete mp3"
    assert not list(destination_directory.glob(".finished.mp3.*.tmp"))


@pytest.mark.asyncio
async def test_bounded_process_reader_drains_multiple_chunks() -> None:
    reader = asyncio.StreamReader()

    async def feed() -> None:
        reader.feed_data(b"a" * 40_000)
        await asyncio.sleep(0)
        reader.feed_data(b"b" * 40_000)
        reader.feed_eof()

    result, _ = await asyncio.gather(
        _read_stream_limited(reader, 100_000, "download_failed"), feed()
    )
    assert result == (b"a" * 40_000) + (b"b" * 40_000)


@pytest.mark.asyncio
async def test_bounded_process_reader_rejects_oversized_output() -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(b"a" * 101)
    reader.feed_eof()
    with pytest.raises(AppError, match="exceeded the safety limit"):
        await _read_stream_limited(reader, 100, "metadata_failed")


def test_applies_machine_readable_download_progress() -> None:
    pipeline = MediaPipeline.__new__(MediaPipeline)
    job = Job(id="job-1", url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", video_id="dQw4w9WgXcQ")

    pipeline._apply_progress(
        job,
        "__YTA_PROGRESS__| 36.4%|1047552|2879602|3972866.1|1",
    )

    assert job.progress == 36.4
    assert job.downloaded_bytes == 1_047_552
    assert job.total_bytes == 2_879_602
    assert job.speed_bytes_per_second == 3_972_866.1
    assert job.eta_seconds == 1


def test_applies_progress_when_optional_values_are_unavailable() -> None:
    pipeline = MediaPipeline.__new__(MediaPipeline)
    job = Job(id="job-1", url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", video_id="dQw4w9WgXcQ")

    pipeline._apply_progress(job, "__YTA_PROGRESS__| 0.1%|3072|NA|NA|NA")

    assert job.progress == 0.1
    assert job.downloaded_bytes == 3_072
    assert job.total_bytes is None
    assert job.speed_bytes_per_second is None
    assert job.eta_seconds is None
