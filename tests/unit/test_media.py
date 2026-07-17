import io

from PIL import Image
from youtube_audio.media import _normalize_cover


def test_cover_is_bounded_jpeg() -> None:
    source = io.BytesIO()
    Image.new("RGBA", (2000, 1000), (3, 169, 244, 128)).save(source, "PNG")
    result = _normalize_cover(source.getvalue())
    assert len(result) <= 2_000_000
    with Image.open(io.BytesIO(result)) as image:
        assert image.format == "JPEG"
        assert image.width <= 1600
        assert image.height <= 1600
