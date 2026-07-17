from pathlib import Path

from youtube_audio.filenames import choose_output_path, safe_stem


def test_normalizes_portable_unicode_filename() -> None:
    assert safe_stem("  Zażółć / AC_DC: Live?\u200b.  ", "abc123") == "Zażółć AC_DC Live"


def test_protects_windows_devices_and_empty_names() -> None:
    assert safe_stem("CON", "abc123") == "_CON"
    assert safe_stem("..", "abc123") == "abc123"
    assert safe_stem("LPT9.txt", "abc123") == "_LPT9.txt"


def test_allocates_collision_without_overwriting(tmp_path: Path) -> None:
    (tmp_path / "Title.mp3").touch()
    assert choose_output_path(tmp_path, "Title", False).name == "Title (2).mp3"
    assert choose_output_path(tmp_path, "Title", True).name == "Title.mp3"
