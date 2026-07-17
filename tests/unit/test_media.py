import asyncio
import io

import pytest
from PIL import Image
from youtube_audio.errors import AppError
from youtube_audio.media import _normalize_cover, _read_stream_limited


def test_cover_is_bounded_jpeg() -> None:
    source = io.BytesIO()
    Image.new("RGBA", (2000, 1000), (3, 169, 244, 128)).save(source, "PNG")
    result = _normalize_cover(source.getvalue())
    assert len(result) <= 2_000_000
    with Image.open(io.BytesIO(result)) as image:
        assert image.format == "JPEG"
        assert image.width <= 1600
        assert image.height <= 1600


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
