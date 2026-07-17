#!/usr/bin/env python3
"""Validate synchronized app, Python, frontend, and optional tag versions."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", help="Git tag, with or without a v prefix")
    args = parser.parse_args()
    config = yaml.safe_load((ROOT / "youtube_audio_downloader/config.yaml").read_text("utf-8"))
    version = str(config["version"])
    package = json.loads(
        (ROOT / "youtube_audio_downloader/rootfs/app/frontend/package.json").read_text("utf-8")
    )
    init = (
        ROOT / "youtube_audio_downloader/rootfs/app/backend/youtube_audio/__init__.py"
    ).read_text("utf-8")
    backend_match = re.search(r'__version__ = "([^"]+)"', init)
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    expected = {
        "frontend package": str(package["version"]),
        "backend package": backend_match.group(1) if backend_match else "missing",
        "Python project": str(project["project"]["version"]),
        "git tag": args.tag.removeprefix("v") if args.tag else version,
    }
    errors = [
        f"{name} is {value}, expected {version}"
        for name, value in expected.items()
        if value != version
    ]
    if config.get("image") != "ghcr.io/misiu/youtube-audio-downloader":
        errors.append("config image is not the expected generic GHCR manifest name")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Version {version} is synchronized.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
