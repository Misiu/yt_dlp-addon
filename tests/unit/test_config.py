from pathlib import Path

import pytest
from youtube_audio.config import Settings
from youtube_audio.errors import AppError


def test_resolves_relative_output_below_media(tmp_path: Path) -> None:
    settings = Settings(data_root=tmp_path / "data", media_root=tmp_path / "media")
    assert settings.resolved_output_directory == (tmp_path / "media" / "youtube_audio").resolve()


@pytest.mark.parametrize("value", ["../escape", "/tmp/escape", "/media/../etc"])
def test_rejects_output_escape(tmp_path: Path, value: str) -> None:
    settings = Settings(
        output_directory=value, data_root=tmp_path / "data", media_root=tmp_path / "media"
    )
    with pytest.raises(AppError, match="inside /media"):
        _ = settings.resolved_output_directory


def test_accepts_valid_absolute_media_path(tmp_path: Path) -> None:
    media = tmp_path / "media"
    settings = Settings(
        output_directory=str(media / "music"), data_root=tmp_path / "data", media_root=media
    )
    assert settings.resolved_output_directory == (media / "music").resolve()
