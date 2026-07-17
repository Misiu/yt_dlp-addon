"""Runtime configuration and storage-boundary validation."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from .errors import AppError


class Settings(BaseModel):
    output_directory: str = Field(default="youtube_audio", min_length=1, max_length=200)
    mp3_quality: int = 320
    history_limit: int = Field(default=100, ge=0, le=10_000)
    overwrite_existing: bool = False
    queue_limit: int = Field(default=100, ge=1, le=1_000)
    download_timeout: int = Field(default=1_800, ge=30, le=7_200)
    filename_max_length: int = Field(default=180, ge=32, le=240)
    data_root: Path = Path("/data")
    media_root: Path = Path("/media")
    frontend_root: Path = Path("/app/frontend")

    @field_validator("mp3_quality")
    @classmethod
    def validate_quality(cls, value: int) -> int:
        if value not in {128, 192, 256, 320}:
            raise ValueError("mp3_quality must be 128, 192, 256, or 320")
        return value

    @property
    def database_path(self) -> Path:
        return self.data_root / "youtube_audio.db"

    @property
    def temp_root(self) -> Path:
        return self.data_root / "tmp"

    @property
    def resolved_output_directory(self) -> Path:
        raw = Path(self.output_directory)
        candidate = raw if raw.is_absolute() else self.media_root / raw
        try:
            resolved = candidate.resolve(strict=False)
            root = self.media_root.resolve(strict=False)
            resolved.relative_to(root)
        except (OSError, ValueError) as exc:
            raise AppError(
                "output_path_invalid", "Output directory must be inside /media."
            ) from exc
        if resolved == root:
            raise AppError(
                "output_path_invalid", "Choose a directory below /media, not /media itself."
            )
        return resolved

    def prepare_directories(self) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.temp_root.mkdir(parents=True, exist_ok=True)
        output = self.resolved_output_directory
        output.mkdir(parents=True, exist_ok=True)
        for directory in (self.data_root, self.temp_root, output):
            if not os.access(directory, os.W_OK):
                raise AppError("storage_unavailable", f"Directory is not writable: {directory}")

    @classmethod
    def load(cls, options_path: Path | None = None) -> Settings:
        path = options_path or Path(os.environ.get("OPTIONS_PATH", "/data/options.json"))
        values: dict[str, object] = {}
        if path.is_file():
            with path.open(encoding="utf-8") as handle:
                loaded = json.load(handle)
            if not isinstance(loaded, dict):
                raise AppError("invalid_configuration", "options.json must contain an object.")
            values.update(loaded)
        overrides = {
            "data_root": os.environ.get("YAD_DATA_ROOT"),
            "media_root": os.environ.get("YAD_MEDIA_ROOT"),
            "frontend_root": os.environ.get("YAD_FRONTEND_ROOT"),
        }
        values.update({key: value for key, value in overrides.items() if value is not None})
        return cls.model_validate(values)
