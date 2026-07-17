import asyncio
import errno
import io
import os
from pathlib import Path

import pytest
from PIL import Image
from youtube_audio.errors import AppError
from youtube_audio.media import _atomic_publish, _normalize_cover, _read_stream_limited


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
