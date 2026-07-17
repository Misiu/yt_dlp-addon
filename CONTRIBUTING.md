# Contributing

Thank you for improving YouTube Audio Downloader. Open an issue before a large behavior/API change. Never use real private URLs, cookies, credentials, or copyrighted test media in commits or CI.

## Development setup

Requirements: Python 3.13, Node.js 24, npm, Docker with BuildKit, and Git.

```bash
python -m venv .venv
python -m pip install --editable ".[dev]"
cd youtube_audio_downloader/rootfs/app/frontend
npm ci
```

Run backend checks from the repository root:

```bash
ruff format --check .
ruff check .
mypy
pytest --cov=youtube_audio
python scripts/validate_repository.py
python scripts/validate_version.py
```

Run frontend checks in its directory:

```bash
npm run lint
npm run check
npm test
npm run build
```

The standard test suite must not contact YouTube. Use mocked adapters or generated media fixtures. A manual authorized end-to-end test may be performed separately.

Build the local smoke image with:

```bash
docker build --tag youtube-audio-downloader:test youtube_audio_downloader
```

## Release discipline

Update `config.yaml`, backend `__version__`, frontend package version, lockfiles, and App changelog together. Run `python scripts/validate_version.py`. Merge only after both architecture builds pass. Create `vX.Y.Z` only when the code for that version is final; the tag workflow builds/pushes architecture images, publishes the generic manifest, then creates the GitHub Release. Do not commit a `config.yaml` version whose image cannot be published.

Use conventional, focused commits where practical. Keep REST fields/error codes backward compatible within a major version and document architectural decisions in `ARCHITECTURE.md`.
