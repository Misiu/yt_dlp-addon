import pytest
from youtube_audio.errors import AppError
from youtube_audio.validation import parse_youtube_url


@pytest.mark.parametrize(
    ("url", "video_id"),
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtube.com/watch?v=dQw4w9WgXcQ&list=ignored", "dQw4w9WgXcQ"),
        ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ?t=1", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ],
)
def test_supported_urls(url: str, video_id: str) -> None:
    canonical, parsed_id = parse_youtube_url(url)
    assert canonical == f"https://www.youtube.com/watch?v={video_id}"
    assert parsed_id == video_id


@pytest.mark.parametrize(
    "url",
    [
        "http://youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com.evil.test/watch?v=dQw4w9WgXcQ",
        "file:///etc/passwd",
        "https://127.0.0.1/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/playlist?list=abc",
        "https://user:pass@youtube.com/watch?v=dQw4w9WgXcQ",
    ],
)
def test_rejects_unsafe_or_unsupported_urls(url: str) -> None:
    with pytest.raises(AppError):
        parse_youtube_url(url)
