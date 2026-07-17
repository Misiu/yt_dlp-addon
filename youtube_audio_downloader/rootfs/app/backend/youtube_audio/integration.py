"""Authenticated Home Assistant integration access and Supervisor discovery."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from .errors import AppError

LOGGER = logging.getLogger(__name__)
API_VERSION = 1
DISCOVERY_SERVICE = "youtube_audio_downloader"
INTERNAL_API_PORT = 8099
_ANNOUNCE_INTERVAL_SECONDS = 86_400
_RETRY_INTERVAL_SECONDS = 30
_CREDENTIALS_FILE = "integration_credentials.json"


@dataclass(frozen=True, slots=True)
class IntegrationCredentials:
    """Stable identity and bearer token shared through Supervisor discovery."""

    instance_id: str
    auth_token: str


def load_or_create_credentials(data_root: Path) -> IntegrationCredentials:
    """Load stable integration credentials or securely create them once."""
    path = data_root / _CREDENTIALS_FILE
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            credentials = IntegrationCredentials(
                instance_id=str(raw["instance_id"]),
                auth_token=str(raw["auth_token"]),
            )
            UUID(credentials.instance_id)
            if len(credentials.auth_token) < 32:
                raise ValueError("authentication token is too short")
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AppError(
                "integration_credentials_invalid",
                "Stored Home Assistant integration credentials are invalid.",
            ) from exc
        return credentials

    credentials = IntegrationCredentials(
        instance_id=str(uuid4()),
        auth_token=secrets.token_urlsafe(32),
    )
    _write_credentials(path, credentials)
    return credentials


def _write_credentials(path: Path, credentials: IntegrationCredentials) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    payload = {
        "instance_id": credentials.instance_id,
        "auth_token": credentials.auth_token,
    }
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise AppError(
            "storage_unavailable",
            "Could not store Home Assistant integration credentials in /data.",
        ) from exc


async def announce_to_supervisor(
    credentials: IntegrationCredentials,
    *,
    supervisor_token: str,
    hostname: str,
    client: httpx.AsyncClient | None = None,
) -> None:
    """Publish the internal authenticated API endpoint through Supervisor discovery."""
    payload = {
        "service": DISCOVERY_SERVICE,
        "config": {
            "host": hostname,
            "port": INTERNAL_API_PORT,
            "auth_token": credentials.auth_token,
            "instance_id": credentials.instance_id,
            "api_version": API_VERSION,
        },
    }
    owns_client = client is None
    runtime_client = client or httpx.AsyncClient(timeout=10)
    try:
        response = await runtime_client.post(
            "http://supervisor/discovery",
            headers={"Authorization": f"Bearer {supervisor_token}"},
            json=payload,
        )
        response.raise_for_status()
    finally:
        if owns_client:
            await runtime_client.aclose()


class SupervisorDiscovery:
    """Announce discovery at startup, retry failures, and refresh it daily."""

    def __init__(self, credentials: IntegrationCredentials) -> None:
        self.credentials = credentials
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        supervisor_token = os.environ.get("SUPERVISOR_TOKEN")
        hostname = os.environ.get("HOSTNAME")
        if not supervisor_token or not hostname:
            LOGGER.info("Supervisor discovery unavailable outside a Home Assistant App")
            return
        self._task = asyncio.create_task(
            self._run(supervisor_token, hostname),
            name="supervisor-discovery",
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task

    async def _run(self, supervisor_token: str, hostname: str) -> None:
        while not self._stop.is_set():
            delay = _ANNOUNCE_INTERVAL_SECONDS
            try:
                await announce_to_supervisor(
                    self.credentials,
                    supervisor_token=supervisor_token,
                    hostname=hostname,
                )
                LOGGER.info(
                    "Announced Home Assistant integration service=%s host=%s port=%d",
                    DISCOVERY_SERVICE,
                    hostname,
                    INTERNAL_API_PORT,
                )
            except httpx.HTTPError as exc:
                delay = _RETRY_INTERVAL_SECONDS
                LOGGER.warning("Home Assistant integration discovery failed: %s", exc)

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except TimeoutError:
                continue
