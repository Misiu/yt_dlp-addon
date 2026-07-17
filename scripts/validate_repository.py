#!/usr/bin/env python3
"""Validate repository metadata not covered by the app linter."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    repository = yaml.safe_load((ROOT / "repository.yaml").read_text("utf-8"))
    assert set(repository) == {"name", "url", "maintainer"}
    assert repository["url"] == "https://github.com/Misiu/yt_dlp-app"
    config = yaml.safe_load((ROOT / "youtube_audio_downloader/config.yaml").read_text("utf-8"))
    assert config["slug"] == "youtube_audio_downloader"
    assert config["arch"] == ["amd64", "aarch64"]
    # Supervisor 2026.07 applies numeric Range validation to bounded strings.
    assert config["schema"]["output_directory"] == "str"
    assert "ports" not in config
    assert not any(
        config.get(key) for key in ("hassio_api", "homeassistant_api", "host_network", "privileged")
    )
    print("Repository metadata is valid.")


if __name__ == "__main__":
    main()
