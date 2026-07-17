# Changelog

All notable changes to this App are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow Semantic Versioning.

## [0.1.1] - 2026-07-17

### Fixed

- Allow Home Assistant Supervisor to save and validate `output_directory` without the `must have a partial ordering` error.

## [0.1.0] - 2026-07-17

### Added

- Home Assistant App repository metadata, translations, AppArmor profile, Ingress configuration, and disabled-by-default direct port.
- Experimental first-release channel pending validation on a real Home Assistant OS test instance.
- Multi-architecture GHCR image build for `amd64` and `aarch64` using the current Home Assistant builder actions.
- Digest-pinned Home Assistant and Node.js images, signed release images, base-signature verification, and dependency vulnerability audits.
- FastAPI REST/SSE backend, durable SQLite FIFO queue, restart recovery, cancellation, history management, and structured errors.
- Isolated `yt-dlp` and ffmpeg processes, atomic MP3 output, safe Unicode filenames, ID3v2.3 metadata, bounded cover art, disk checks, timeouts, and cleanup.
- Responsive English/Polish Lit and Web Awesome interface with light/dark modes and accessibility support.
- Backend/frontend tests, strict lint/type checks, App metadata validation, image smoke build, dependency automation, and release workflow.
- Ingress source enforcement and Home Assistant-recommended 128x128 icon and 250x100 logo assets.

[0.1.1]: https://github.com/Misiu/yt_dlp-app/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Misiu/yt_dlp-app/releases/tag/v0.1.0
