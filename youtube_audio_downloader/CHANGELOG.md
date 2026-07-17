# Changelog

All notable changes to this App are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow Semantic Versioning.

## [0.1.5] - 2026-07-17

### Added

- Add labelled history icon actions with hover/focus tooltips for downloading again and removing a history row.
- Require confirmation before a history redownload, then create a fresh queue job that forces replacement of the matching destination file.

### Fixed

- Follow the language selected in the Home Assistant profile when running through Ingress, with live language updates and browser-locale fallback.

## [0.1.4] - 2026-07-17

### Added

- Announce an authenticated internal API through Home Assistant Supervisor discovery for the companion integration.
- Persist a stable instance UUID and dedicated bearer token in App data, and expose API compatibility metadata without exposing the token.
- Document the complete companion-integration contract, actions, entities, security boundary, and test expectations.

### Changed

- Show only the active stage below the current-download progress bar instead of byte and ETA placeholders.
- Permit non-Ingress access only to `/api/*` with the discovered bearer token; the port remains internal and unpublished.

### Fixed

- Split conventional `Artist - Title` video titles into correct track and artist tags, with the source channel as fallback.
- Stop assigning every download to a synthetic `YouTube` album, which caused media libraries to group unrelated tracks and reuse one album cover.
- Write ID3v2.3-compatible text and APIC description encodings while retaining a distinct embedded JPEG cover in every file.

## [0.1.3] - 2026-07-17

### Fixed

- Parse machine-readable yt-dlp progress reports so percentage, byte counts, speed, and ETA update during downloads.

### Changed

- Apply `job_updated` SSE payloads directly in the Web UI for immediate progress updates while retaining REST snapshots and polling fallback.
- Log each yt-dlp progress report with job ID, percentage, byte counts, speed, and ETA for diagnostics.

## [0.1.2] - 2026-07-17

### Fixed

- Publish completed MP3 files atomically on the `/media` filesystem instead of attempting an unsupported cross-filesystem rename from `/data`.

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

[0.1.5]: https://github.com/Misiu/yt_dlp-app/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/Misiu/yt_dlp-app/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/Misiu/yt_dlp-app/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/Misiu/yt_dlp-app/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/Misiu/yt_dlp-app/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Misiu/yt_dlp-app/releases/tag/v0.1.0
