import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from youtube_audio.errors import AppError
from youtube_audio.integration import (
    API_VERSION,
    DISCOVERY_SERVICE,
    INTERNAL_API_PORT,
    announce_to_supervisor,
    load_or_create_credentials,
)


def test_credentials_are_created_once_and_remain_stable(tmp_path: Path) -> None:
    first = load_or_create_credentials(tmp_path)
    second = load_or_create_credentials(tmp_path)

    assert second == first
    assert UUID(first.instance_id)
    assert len(first.auth_token) >= 32
    stored = json.loads((tmp_path / "integration_credentials.json").read_text(encoding="utf-8"))
    assert stored == {
        "instance_id": first.instance_id,
        "auth_token": first.auth_token,
    }


def test_invalid_stored_credentials_stop_startup(tmp_path: Path) -> None:
    (tmp_path / "integration_credentials.json").write_text("{}", encoding="utf-8")

    with pytest.raises(AppError, match="credentials are invalid"):
        load_or_create_credentials(tmp_path)


@pytest.mark.asyncio
async def test_supervisor_discovery_contains_internal_authenticated_endpoint(
    tmp_path: Path,
) -> None:
    credentials = load_or_create_credentials(tmp_path)
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["Authorization"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"uuid": "discovery-id"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await announce_to_supervisor(
            credentials,
            supervisor_token="supervisor-secret",  # noqa: S106 - synthetic test value
            hostname="example-app-host",
            client=client,
        )

    assert captured["authorization"] == "Bearer supervisor-secret"
    assert captured["payload"] == {
        "service": DISCOVERY_SERVICE,
        "config": {
            "host": "example-app-host",
            "port": INTERNAL_API_PORT,
            "auth_token": credentials.auth_token,
            "instance_id": credentials.instance_id,
            "api_version": API_VERSION,
        },
    }
