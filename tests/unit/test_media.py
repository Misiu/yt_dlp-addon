import asyncio
import errno
import io
import os
from pathlib import Path

import pytest
import youtube_audio.media as media
from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, TPE2, TXXX
from PIL import Image
from youtube_audio.errors import AppError
from youtube_audio.media import (
    MediaPipeline,
    _artist_and_title,
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


@pytest.mark.parametrize(
    ("source_title", "fallback_artist", "expected_artist", "expected_title"),
    [
        (
            "GIGI D'AGOSTINO - L'AMOUR TOUJOURS ( OFFICIAL VIDEO )",
            "GIGI D'AGOSTINO",
            "GIGI D'AGOSTINO",
            "L'AMOUR TOUJOURS",
        ),
        (
            "Anyma & Rebūke \u2013 Syren [Live from Afterlife Tomorrowland]",
            "Afterlife",
            "Anyma & Rebūke",
            "Syren [Live from Afterlife Tomorrowland]",
        ),
        (
            "WEEKEND - Halo Tu Londyn 🔥 NOWOŚĆ 2026 (FAIR PLAY REMIX)",
            "Fair Play Official",
            "WEEKEND",
            "Halo Tu Londyn 🔥 NOWOŚĆ 2026 (FAIR PLAY REMIX)",
        ),
        ("The Riddle", "zyxdance", "zyxdance", "The Riddle"),
    ],
)
def test_extracts_artist_and_track_title(
    source_title: str,
    fallback_artist: str,
    expected_artist: str,
    expected_title: str,
) -> None:
    assert _artist_and_title(source_title, fallback_artist, "video-id") == (
        expected_artist,
        expected_title,
    )


def test_applies_parsed_metadata_to_job() -> None:
    job = Job(
        id="job-1",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        video_id="dQw4w9WgXcQ",
    )

    MediaPipeline._apply_metadata(
        job,
        {
            "title": "Gigi D'Agostino - The Riddle (Official Video)",
            "channel": "zyxdance",
        },
    )

    assert job.source_title == "Gigi D'Agostino - The Riddle (Official Video)"
    assert job.artist == "Gigi D'Agostino"
    assert job.title == "The Riddle"
    assert job.channel == "zyxdance"


def test_writes_track_tags_without_album_and_preserves_cover(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "track.mp3"

    class FakeAudio:
        def __init__(self) -> None:
            self.tags = ID3()
            self.tags.add(TALB(encoding=1, text="YouTube"))
            self.tags.add(TPE2(encoding=1, text="YouTube"))
            self.tags.add(APIC(encoding=1, mime="image/png", type=3, desc="Old", data=b"old"))
            self.saved_version: int | None = None

        def save(self, *, v2_version: int) -> None:
            self.saved_version = v2_version
            self.tags.save(output, v2_version=v2_version)

    audio = FakeAudio()
    monkeypatch.setattr(media, "MP3", lambda _path: audio)
    source_cover = io.BytesIO()
    Image.new("RGB", (320, 180), (12, 120, 220)).save(source_cover, "PNG")
    cover = _normalize_cover(source_cover.getvalue())
    job = Job(
        id="job-1",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        video_id="dQw4w9WgXcQ",
        title="The Riddle",
        artist="Gigi D'Agostino",
        channel="zyxdance",
        upload_date="20000101",
    )

    MediaPipeline._tag_mp3(output, job, cover)

    assert audio.saved_version == 3
    saved = ID3(output)
    assert saved.version == (2, 3, 0)
    assert saved.getall("TALB") == []
    assert saved.getall("TPE2") == []
    assert saved.getall("TIT2")[0].text == ["The Riddle"]
    assert isinstance(saved.getall("TIT2")[0], TIT2)
    assert saved.getall("TIT2")[0].encoding == 1
    assert saved.getall("TPE1")[0].text == ["Gigi D'Agostino"]
    assert isinstance(saved.getall("TPE1")[0], TPE1)
    embedded = saved.getall("APIC")[0]
    assert isinstance(embedded, APIC)
    assert embedded.encoding == 0
    assert embedded.desc == "Cover"
    assert embedded.mime == "image/jpeg"
    assert embedded.type == 3
    assert embedded.data == cover
    source_id = saved.getall("TXXX:YouTube Video ID")[0]
    assert isinstance(source_id, TXXX)
    assert source_id.encoding == 0
    assert source_id.desc == "YouTube Video ID"
    assert source_id.text == ["dQw4w9WgXcQ"]
    with Image.open(io.BytesIO(embedded.data)) as image:
        assert image.format == "JPEG"
        assert image.size == (320, 180)
