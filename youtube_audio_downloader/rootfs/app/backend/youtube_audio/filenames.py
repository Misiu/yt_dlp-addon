"""Portable, deterministic output naming."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

_INVALID = re.compile(r'[<>:"/\\|?*]')
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_ZERO_WIDTH = re.compile("[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
_SPACES = re.compile(r"\s+")
_DEVICE = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.IGNORECASE)


def safe_stem(title: str | None, video_id: str, max_length: int = 180) -> str:
    value = unicodedata.normalize("NFC", title or video_id)
    value = _ZERO_WIDTH.sub("", value)
    value = _CONTROL.sub("", value)
    value = _INVALID.sub(" ", value)
    value = _SPACES.sub(" ", value).strip(" .")
    if not value or value in {".", ".."}:
        value = video_id
    if _DEVICE.fullmatch(value):
        value = f"_{value}"
    value = value[:max_length].rstrip(" .")
    return value or video_id


def choose_output_path(directory: Path, stem: str, overwrite: bool) -> Path:
    candidate = directory / f"{stem}.mp3"
    if overwrite or not candidate.exists():
        return candidate
    for number in range(2, 10_000):
        candidate = directory / f"{stem} ({number}).mp3"
        if not candidate.exists():
            return candidate
    raise RuntimeError("Unable to allocate a unique output filename")
