"""Child-process media pipeline, thumbnail handling, and ID3 tagging."""

from __future__ import annotations

import asyncio
import io
import ipaddress
import json
import logging
import os
import re
import shutil
import signal
import socket
import sys
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from mutagen.id3 import APIC, COMM, ID3, TALB, TDRC, TIT2, TPE1, TXXX, WOAS
from mutagen.mp3 import MP3
from PIL import Image

from .config import Settings
from .errors import AppError
from .filenames import choose_output_path, safe_stem
from .models import Job, JobState

LOGGER = logging.getLogger(__name__)
ProgressCallback = Callable[[Job], Awaitable[None]]
_PERCENT = re.compile(r"(?P<percent>\d{1,3}(?:\.\d+)?)%")
_PROGRESS_PREFIX = "__YTA_PROGRESS__|"
_THUMBNAIL_HOSTS = {
    "i.ytimg.com",
    "i1.ytimg.com",
    "i2.ytimg.com",
    "i3.ytimg.com",
    "i4.ytimg.com",
    "img.youtube.com",
}
_KILL_SIGNAL: signal.Signals = getattr(signal, "SIGKILL", signal.SIGTERM)


class CancelledError(Exception):
    """Raised after a requested process cancellation."""


class MediaPipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._process: asyncio.subprocess.Process | None = None
        self._cancel_requested = False

    async def cancel(self) -> None:
        self._cancel_requested = True
        process = self._process
        if process is not None and process.returncode is None:
            self._signal_process(process, signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                self._signal_process(process, _KILL_SIGNAL)
                await process.wait()

    @staticmethod
    def _signal_process(
        process: asyncio.subprocess.Process, requested_signal: signal.Signals
    ) -> None:
        try:
            if os.name == "posix":
                kill_process_group: Any = getattr(os, "killpg", None)
                if kill_process_group is not None:
                    kill_process_group(process.pid, requested_signal)
                else:
                    process.send_signal(requested_signal)
            elif requested_signal == _KILL_SIGNAL:
                process.kill()
            else:
                process.terminate()
        except ProcessLookupError:
            return

    def _raise_if_cancelled(self) -> None:
        if self._cancel_requested:
            raise CancelledError

    async def execute(self, job: Job, update: ProgressCallback) -> Job:
        self._cancel_requested = False
        work = self.settings.temp_root / job.id
        await asyncio.to_thread(work.mkdir, parents=True, exist_ok=True)
        try:
            job.state = JobState.EXTRACTING_METADATA
            job.progress = None
            await update(job)
            metadata = await self._extract_metadata(job.url)
            self._raise_if_cancelled()
            self._apply_metadata(job, metadata)
            await update(job)
            self._ensure_space(estimated_bytes=self._estimated_space(metadata))

            job.state = JobState.DOWNLOADING
            job.progress = 0
            await update(job)
            source = await self._download(job, work, update)
            self._raise_if_cancelled()

            job.state = JobState.PROCESSING
            job.progress = None
            await update(job)
            encoded = work / "encoded.mp3"
            await self._convert(source, encoded)
            self._raise_if_cancelled()

            job.state = JobState.EMBEDDING_METADATA
            await update(job)
            cover: bytes | None = None
            if job.thumbnail_url:
                try:
                    cover = await self._fetch_cover(job.thumbnail_url)
                except Exception as exc:  # cover failure must not fail the job
                    LOGGER.warning("Cover art skipped for job %s: %s", job.id, exc)
                    job.warning_message = "The MP3 was completed without cover art."
            await asyncio.to_thread(self._tag_mp3, encoded, job, cover)
            self._raise_if_cancelled()

            stem = safe_stem(job.title, job.video_id, self.settings.filename_max_length)
            destination = await asyncio.to_thread(
                choose_output_path,
                self.settings.resolved_output_directory,
                stem,
                self.settings.overwrite_existing,
            )
            try:
                await asyncio.to_thread(_atomic_publish, encoded, destination)
            except OSError as exc:
                raise AppError(
                    "storage_unavailable", "Could not save the completed MP3 to /media."
                ) from exc
            job.output_file = destination.relative_to(self.settings.media_root).as_posix()
            job.file_size = await asyncio.to_thread(_file_size, destination)
            job.progress = 100
            return job
        except CancelledError:
            raise
        finally:
            await asyncio.to_thread(shutil.rmtree, work, True)
            self._process = None

    async def _extract_metadata(self, url: str) -> dict[str, Any]:
        args = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--dump-single-json",
            "--skip-download",
            "--no-playlist",
            "--no-warnings",
            "--js-runtimes",
            "node",
            "--",
            url,
        ]
        stdout, _stderr = await self._communicate_bounded(
            args,
            2_000_000,
            128_000,
            failure_code="metadata_failed",
            failure_message="YouTube metadata extraction failed.",
        )
        try:
            metadata: dict[str, Any] = json.loads(stdout)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise AppError("metadata_failed", "Could not read video metadata.") from exc
        if metadata.get("_type") == "playlist":
            raise AppError("metadata_failed", "Playlist downloads are not supported.")
        if not metadata.get("id"):
            raise AppError("metadata_failed", "The video metadata did not include an ID.")
        return metadata

    async def _communicate_bounded(
        self,
        args: list[str],
        stdout_limit: int,
        stderr_limit: int,
        *,
        failure_code: str = "download_failed",
        failure_message: str = "The media operation failed.",
    ) -> tuple[str, str]:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **_process_group_options(),
        )
        self._process = process

        tasks: list[asyncio.Task[Any]] = []
        try:
            async with asyncio.timeout(self.settings.download_timeout):
                tasks = [
                    asyncio.create_task(
                        _read_stream_limited(process.stdout, stdout_limit, failure_code)
                    ),
                    asyncio.create_task(
                        _read_stream_limited(process.stderr, stderr_limit, failure_code)
                    ),
                    asyncio.create_task(process.wait()),
                ]
                stdout_bytes, stderr_bytes, code = await asyncio.gather(*tasks)
        except TimeoutError as exc:
            await self.cancel()
            raise AppError("download_failed", "The operation timed out.") from exc
        except AppError:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        if self._cancel_requested:
            raise CancelledError
        if code != 0:
            detail = stderr_bytes.decode("utf-8", "replace").strip()[-500:]
            LOGGER.warning("Media process failed: %s", detail)
            raise AppError(failure_code, failure_message)
        return (
            stdout_bytes.decode("utf-8", "replace"),
            stderr_bytes.decode("utf-8", "replace"),
        )

    async def _download(self, job: Job, work: Path, update: ProgressCallback) -> Path:
        output = str(work / "source.%(ext)s")
        args = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--no-playlist",
            "--no-warnings",
            "--newline",
            "--progress",
            "--js-runtimes",
            "node",
            "--progress-template",
            f"download:{_PROGRESS_PREFIX}%(progress._percent_str)s|%(progress.downloaded_bytes)s|%(progress.total_bytes,progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s",
            "--format",
            "bestaudio/best",
            "--output",
            output,
            "--",
            job.url,
        ]
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            **_process_group_options(),
        )
        self._process = process
        try:
            async with asyncio.timeout(self.settings.download_timeout):
                assert process.stdout is not None
                async for raw_line in process.stdout:
                    if self._cancel_requested:
                        await self.cancel()
                        raise CancelledError
                    line = raw_line.decode("utf-8", "replace").strip()
                    if line.startswith(_PROGRESS_PREFIX):
                        self._apply_progress(job, line)
                        LOGGER.info(
                            "Download progress id=%s percent=%s downloaded=%s total=%s "
                            "speed=%s eta=%s",
                            job.id,
                            job.progress,
                            job.downloaded_bytes,
                            job.total_bytes,
                            job.speed_bytes_per_second,
                            job.eta_seconds,
                        )
                        await update(job)
                code = await process.wait()
        except TimeoutError as exc:
            await self.cancel()
            raise AppError("download_failed", "The download timed out.") from exc
        if self._cancel_requested:
            raise CancelledError
        if code != 0:
            raise AppError("download_failed", "The audio download failed.")
        candidates = await asyncio.to_thread(_find_source_files, work)
        if len(candidates) != 1:
            raise AppError("download_failed", "The downloaded audio file was not found.")
        return candidates[0]

    @staticmethod
    def _number(value: str, cast: type[int] | type[float]) -> int | float | None:
        if value in {"NA", "None", "", "N/A"}:
            return None
        try:
            return cast(float(value))
        except ValueError:
            return None

    def _apply_progress(self, job: Job, line: str) -> None:
        values = line.removeprefix(_PROGRESS_PREFIX).split("|")
        if values:
            match = _PERCENT.search(values[0])
            job.progress = min(100.0, float(match.group("percent"))) if match else None
        if len(values) >= 5:
            downloaded = self._number(values[1], int)
            total = self._number(values[2], int)
            speed = self._number(values[3], float)
            eta = self._number(values[4], float)
            job.downloaded_bytes = int(downloaded) if downloaded is not None else None
            job.total_bytes = int(total) if total is not None else None
            job.speed_bytes_per_second = float(speed) if speed is not None else None
            job.eta_seconds = float(eta) if eta is not None else None

    async def _convert(self, source: Path, destination: Path) -> None:
        args = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-map_metadata",
            "-1",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            f"{self.settings.mp3_quality}k",
            str(destination),
        ]
        stdout, stderr = await self._communicate_bounded(
            args,
            16_000,
            128_000,
            failure_code="conversion_failed",
            failure_message="ffmpeg could not convert the audio to MP3.",
        )
        if stdout:
            LOGGER.debug("ffmpeg output: %s", stdout[-500:])
        if stderr:
            LOGGER.debug("ffmpeg diagnostics: %s", stderr[-500:])
        if not await asyncio.to_thread(_is_nonempty_file, destination):
            raise AppError("conversion_failed", "ffmpeg did not create a valid MP3 file.")

    @staticmethod
    def _apply_metadata(job: Job, data: dict[str, Any]) -> None:
        job.title = _limited_text(data.get("title"), 500)
        job.channel = _limited_text(data.get("channel") or data.get("uploader"), 300)
        job.uploader = _limited_text(data.get("uploader"), 300)
        job.upload_date = _limited_text(data.get("upload_date"), 16)
        job.description = _limited_text(data.get("description"), 20_000)
        duration = data.get("duration")
        job.duration_seconds = float(duration) if isinstance(duration, int | float) else None
        thumbnails = data.get("thumbnails") or []
        valid = [item for item in thumbnails if isinstance(item, dict) and item.get("url")]
        if valid:
            best = max(valid, key=lambda item: (item.get("width") or 0) * (item.get("height") or 0))
            job.thumbnail_url = str(best["url"])

    @staticmethod
    def _estimated_space(metadata: dict[str, Any]) -> int:
        duration = metadata.get("duration")
        if isinstance(duration, int | float):
            return max(100_000_000, int(float(duration) * 320_000 / 8 * 4))
        return 500_000_000

    def _ensure_space(self, estimated_bytes: int) -> None:
        media_free = shutil.disk_usage(self.settings.resolved_output_directory).free
        data_free = shutil.disk_usage(self.settings.temp_root).free
        if media_free < max(100_000_000, estimated_bytes // 3) or data_free < estimated_bytes:
            raise AppError("insufficient_space", "There is not enough free space for this job.")

    async def _fetch_cover(self, url: str) -> bytes:
        await _validate_public_https_url(url)
        limits = httpx.Limits(max_connections=2, max_keepalive_connections=1)
        async with httpx.AsyncClient(timeout=20, follow_redirects=False, limits=limits) as client:
            async with client.stream(
                "GET", url, headers={"User-Agent": "YouTubeAudioDownloader/0.1"}
            ) as response:
                response.raise_for_status()
                if response.headers.get("content-type", "").split(";", 1)[0] not in {
                    "image/jpeg",
                    "image/png",
                    "image/webp",
                }:
                    raise ValueError("unsupported thumbnail content type")
                buffer = bytearray()
                async for chunk in response.aiter_bytes():
                    buffer.extend(chunk)
                    if len(buffer) > 2_000_000:
                        raise ValueError("thumbnail exceeds 2 MB")
        return await asyncio.to_thread(_normalize_cover, bytes(buffer))

    @staticmethod
    def _tag_mp3(path: Path, job: Job, cover: bytes | None) -> None:
        audio = MP3(path)  # type: ignore[no-untyped-call]
        if audio.tags is None:
            audio.add_tags()  # type: ignore[no-untyped-call]
        tags = audio.tags
        assert isinstance(tags, ID3)
        tags.delall("TIT2")
        tags.add(TIT2(encoding=3, text=job.title or job.video_id))
        if job.channel or job.uploader:
            tags.add(TPE1(encoding=3, text=job.channel or job.uploader or ""))
        tags.add(TALB(encoding=3, text="YouTube"))
        if job.upload_date and len(job.upload_date) >= 4:
            tags.add(TDRC(encoding=3, text=job.upload_date[:4]))
        if job.description:
            tags.add(COMM(encoding=3, lang="eng", desc="Description", text=job.description[:4_000]))
        tags.add(WOAS(url=job.url))
        tags.add(TXXX(encoding=3, desc="YouTube Video ID", text=job.video_id))
        if cover:
            tags.delall("APIC")
            tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover))
        audio.save(v2_version=3)


def _atomic_publish(source: Path, destination: Path) -> None:
    """Copy into the destination filesystem, then atomically publish the MP3."""
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with source.open("rb") as input_file, os.fdopen(file_descriptor, "wb") as output_file:
            file_descriptor = -1
            shutil.copyfileobj(input_file, output_file, length=1024 * 1024)
            output_file.flush()
            os.fsync(output_file.fileno())
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        temporary.unlink(missing_ok=True)


def _fsync_directory(directory: Path) -> None:
    """Best-effort directory sync after the atomic rename."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        file_descriptor = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(file_descriptor)
    except OSError:
        pass
    finally:
        os.close(file_descriptor)


def _limited_text(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.replace("\x00", "").split())
    return cleaned[:limit] or None


async def _validate_public_https_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("thumbnail URL must use HTTPS")
    if parts.hostname.lower().rstrip(".") not in _THUMBNAIL_HOSTS:
        raise ValueError("thumbnail host is not allowlisted")
    loop = asyncio.get_running_loop()
    records = await loop.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)
    if not records:
        raise ValueError("thumbnail host did not resolve")
    for record in records:
        address = ipaddress.ip_address(record[4][0])
        if not address.is_global:
            raise ValueError("thumbnail URL resolved to a non-public address")


def _normalize_cover(value: bytes) -> bytes:
    with Image.open(io.BytesIO(value)) as opened:
        image: Image.Image = opened.copy()
    image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    if image.mode != "RGB":
        background = Image.new("RGB", image.size, "white")
        if "A" in image.getbands():
            background.paste(image, mask=image.getchannel("A"))
        else:
            background.paste(image)
        image = background
    for quality in (88, 80, 72, 64):
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=quality, optimize=True)
        if output.tell() <= 2_000_000:
            return output.getvalue()
    raise ValueError("normalized thumbnail exceeds 2 MB")


def _find_source_files(work: Path) -> list[Path]:
    return [
        path
        for path in work.glob("source.*")
        if not path.name.endswith((".part", ".ytdl")) and path.is_file()
    ]


def _is_nonempty_file(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _file_size(path: Path) -> int:
    return path.stat().st_size


async def _read_stream_limited(
    stream: asyncio.StreamReader | None, limit: int, failure_code: str
) -> bytes:
    if stream is None:
        return b""
    value = bytearray()
    while True:
        chunk = await stream.read(min(65_536, limit + 1 - len(value)))
        if not chunk:
            return bytes(value)
        value.extend(chunk)
        if len(value) > limit:
            raise AppError(failure_code, "Process output exceeded the safety limit.")


def _process_group_options() -> dict[str, Any]:
    return {"start_new_session": True} if os.name == "posix" else {}
