"""Domain and API models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class JobState(StrEnum):
    QUEUED = "queued"
    EXTRACTING_METADATA = "extracting_metadata"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    EMBEDDING_METADATA = "embedding_metadata"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_STATES = {
    JobState.EXTRACTING_METADATA,
    JobState.DOWNLOADING,
    JobState.PROCESSING,
    JobState.EMBEDDING_METADATA,
}
TERMINAL_STATES = {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}


class Job(BaseModel):
    model_config = ConfigDict(use_enum_values=False)

    id: str
    url: str
    video_id: str
    state: JobState = JobState.QUEUED
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    title: str | None = None
    channel: str | None = None
    uploader: str | None = None
    upload_date: str | None = None
    description: str | None = None
    duration_seconds: float | None = None
    thumbnail_url: str | None = None
    progress: float | None = 0
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    speed_bytes_per_second: float | None = None
    eta_seconds: float | None = None
    output_file: str | None = None
    file_size: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    warning_message: str | None = None

    @property
    def elapsed_seconds(self) -> float | None:
        if self.started_at is None:
            return None
        end = self.finished_at or utc_now()
        return max(0.0, (end - self.started_at).total_seconds())


class DownloadRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2_048)


class BatchDownloadRequest(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=50)


class ClearHistoryRequest(BaseModel):
    confirm: bool = False


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class Page(BaseModel):
    items: list[Job]
    page: int
    page_size: int
    total: int


class Event(BaseModel):
    type: str
    data: dict[str, Any]
