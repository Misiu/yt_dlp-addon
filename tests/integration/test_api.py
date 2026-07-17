import asyncio
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from youtube_audio.config import Settings
from youtube_audio.main import create_app
from youtube_audio.media import CancelledError
from youtube_audio.models import Job, JobState


class BlockingPipeline:
    def __init__(self) -> None:
        self.cancelled = asyncio.Event()

    async def execute(self, job: Job, update: object) -> Job:
        job.state = JobState.DOWNLOADING
        await self.cancelled.wait()
        raise CancelledError

    async def cancel(self) -> None:
        self.cancelled.set()


def make_app(tmp_path: Path) -> FastAPI:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    settings = Settings(
        data_root=tmp_path / "data",
        media_root=tmp_path / "media",
        frontend_root=frontend,
    )
    app = create_app(settings)
    app.state.queue.pipeline = BlockingPipeline()
    return app


def ingress_client(app: FastAPI, *, root_path: str = "") -> TestClient:
    return TestClient(app, root_path=root_path, client=("172.30.32.2", 50_000))


def test_health_and_effective_config(tmp_path: Path) -> None:
    with ingress_client(make_app(tmp_path)) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok", "version": "0.1.0"}
        config = client.get("/api/v1/config").json()
        assert config["output_directory"] == "youtube_audio"
        assert config["concurrent_downloads"] == 1


def test_invalid_and_duplicate_downloads(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with ingress_client(app) as client:
        invalid = client.post("/api/v1/downloads", json={"url": "https://example.com/video"})
        assert invalid.status_code == 400
        assert invalid.json()["error"]["code"] == "unsupported_host"

        first = client.post("/api/v1/downloads", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
        assert first.status_code == 202
        duplicate = client.post(
            "/api/v1/downloads",
            json={"url": "https://youtube.com/watch?v=dQw4w9WgXcQ"},
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "duplicate_job"


def test_batch_downloads_are_validated_and_enqueued_atomically(tmp_path: Path) -> None:
    with ingress_client(make_app(tmp_path)) as client:
        invalid = client.post(
            "/api/v1/downloads/batch",
            json={
                "urls": [
                    "https://youtu.be/dQw4w9WgXcQ",
                    "https://example.com/not-youtube",
                ]
            },
        )
        assert invalid.status_code == 400
        assert client.get("/api/v1/queue").json()["items"] == []

        duplicate = client.post(
            "/api/v1/downloads/batch",
            json={
                "urls": [
                    "https://youtu.be/dQw4w9WgXcQ",
                    "https://youtube.com/watch?v=dQw4w9WgXcQ",
                ]
            },
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "duplicate_job"

        accepted = client.post(
            "/api/v1/downloads/batch",
            json={
                "urls": [
                    "https://youtu.be/dQw4w9WgXcQ",
                    "https://youtube.com/shorts/9bZkp7q19f0",
                ]
            },
        )
        assert accepted.status_code == 202
        assert accepted.json()["accepted"] == 2
        assert len(accepted.json()["items"]) == 2


def test_ingress_style_prefixed_path_is_not_hard_coded(tmp_path: Path) -> None:
    with ingress_client(make_app(tmp_path), root_path="/ingress/token") as client:
        response = client.get("/api/health")
        assert response.status_code == 200


def test_rejects_clients_outside_ingress_network(tmp_path: Path) -> None:
    with TestClient(make_app(tmp_path), client=("172.30.32.3", 50_000)) as client:
        response = client.get("/api/v1/status")
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "ingress_required"


def test_queue_cancel_history_and_clear_api(tmp_path: Path) -> None:
    with ingress_client(make_app(tmp_path)) as client:
        first = client.post(
            "/api/v1/downloads", json={"url": "https://youtu.be/dQw4w9WgXcQ"}
        ).json()
        deadline = time.monotonic() + 2
        while client.get("/api/v1/status").json()["current"] is None:
            assert time.monotonic() < deadline
            time.sleep(0.01)

        second = client.post(
            "/api/v1/downloads", json={"url": "https://youtu.be/9bZkp7q19f0"}
        ).json()
        assert client.delete(f"/api/v1/queue/{second['id']}").status_code == 204
        assert client.post(f"/api/v1/downloads/{first['id']}/cancel").status_code == 202

        deadline = time.monotonic() + 2
        details = client.get(f"/api/v1/downloads/{first['id']}").json()
        while details["state"] != "cancelled":
            assert time.monotonic() < deadline
            time.sleep(0.01)
            details = client.get(f"/api/v1/downloads/{first['id']}").json()
        history = client.get("/api/v1/history?state=cancelled").json()
        assert history["total"] == 1

        assert (
            client.request("DELETE", "/api/v1/history", json={"confirm": False}).status_code == 400
        )
        cleared = client.request("DELETE", "/api/v1/history", json={"confirm": True})
        assert cleared.status_code == 200
        assert cleared.json() == {"deleted": 1}


def test_request_validation_uses_stable_error_envelope(tmp_path: Path) -> None:
    with ingress_client(make_app(tmp_path)) as client:
        response = client.post("/api/v1/downloads", json={})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"
