# YouTube Audio Downloader documentation

## Configuration

Configuration has a single source of truth: the Home Assistant App **Configuration** tab, stored by Supervisor in `/data/options.json`.

| Option | Type | Default | Notes |
|---|---|---|---|
| `output_directory` | string | `youtube_audio` | Relative to `/media`; contained absolute paths are accepted. `/media`, traversal, and paths outside the mount are rejected. |
| `mp3_quality` | enum | `320` | 128, 192, 256, or 320 kbit/s. A higher output bitrate does not improve a lower-quality source. |
| `history_limit` | integer | `100` | 0–10,000 terminal records; trimming never deletes MP3 files. |
| `overwrite_existing` | boolean | `false` | Atomically replaces a same-named MP3 when true; otherwise allocates a suffix. |

The output directory is created automatically and checked for write access at startup. One download is processed at a time.

The Ingress service listens on container-internal port 8099. No host port is published or configurable. Application traffic is accepted only from the authenticated Supervisor Ingress proxy; container loopback is reserved for the Docker health check. A future companion integration will need a deliberately authenticated internal channel. CORS is disabled.

## Web UI

Select **Open Web UI**, paste one HTTPS YouTube video/watch/short URL or up to 50 unique links (one per line), and press **Add to queue**. The complete batch is validated before any item is inserted. Enable **Show in sidebar** on the App Info page to add the configured **YouTube Audio** menu entry. The page shows the active stage, determinate download progress when yt-dlp provides totals, byte counts, speed, ETA, waiting jobs, and paged terminal history. It reconnects to Server-Sent Events automatically and uses 10-second REST polling only while the event stream is unavailable.

The UI detects Polish from the browser locale and otherwise uses English. It supports light/dark preferences, keyboard navigation, visible focus, reduced motion, semantic status announcements, responsive card rows, and relative Ingress paths.

## Processing and file naming

The worker first extracts bounded metadata, estimates temporary disk requirements, downloads `bestaudio/best` with `--no-playlist`, converts it using ffmpeg/libmp3lame, writes ID3v2.3 tags, and atomically publishes the file. Current yt-dlp YouTube challenge solving uses the bundled Node.js runtime and the EJS scripts pinned with `yt-dlp[default]`; neither is downloaded or upgraded at App startup. Source, temporary MP3, final MP3, and cover may coexist during processing.

Titles keep Unicode but remove control and zero-width characters, Windows-invalid punctuation, separators, trailing spaces/dots, `.`/`..`, and reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`). Multiple whitespace is collapsed. Without overwrite, collisions become `Title (2).mp3`, `Title (3).mp3`, and so on.

## Metadata and cover

When present, the MP3 receives:

- title (`TIT2`), channel/uploader (`TPE1`), and album `YouTube` (`TALB`);
- publication year (`TDRC`), a normalized description capped at 4,000 characters (`COMM`), source URL (`WOAS`), and video ID (`TXXX`);
- a front-cover `APIC` JPEG, bounded to 1600×1600 and 2 MB.

Thumbnail fetch/convert failure is non-fatal. The job completes without cover and retains a warning.

## Queue, history, and restart policy

SQLite uses WAL mode at `/data/youtube_audio.db`. Queued jobs are FIFO. A unique active `video_id` prevents duplicate waiting/active work, while completed videos may be submitted again. The database is committed before live events are sent.

After a restart, any job in metadata/download/conversion/tagging is reset to `queued`, marked `restart_requeued`, and retried from the beginning. Its per-job temporary directory prevents publication of a partial MP3. Items under `/data/tmp` older than 24 hours are removed at startup.

Deleting a queued job is allowed only before it becomes active. Cancelling the current job terminates the current child process, waits five seconds, then kills it if necessary. Deleting or clearing history never removes media.

## REST API

For Web UI use, resolve all URLs relative to the current Ingress document. JSON error responses use:

```json
{"error":{"code":"invalid_url","message":"The provided URL is not supported."}}
```

| Method | Path | Result |
|---|---|---|
| GET | `/api/health` | Fast local health and App version. |
| GET | `/api/v1/info` | Safe version, architecture, output and queue diagnostics. |
| GET | `/api/v1/config` | Effective read-only App options. |
| POST | `/api/v1/downloads` | Body `{"url":"https://..."}`; returns 202 and job ID. |
| POST | `/api/v1/downloads/batch` | Body `{"urls":["https://...", "https://..."]}`; atomically validates and queues up to 50 unique videos. |
| GET | `/api/v1/status` | Overall state, queue length, and active job. |
| GET | `/api/v1/queue` | Waiting and transient jobs. |
| GET | `/api/v1/history?page=1&page_size=25&state=completed` | Paged terminal jobs; state is optional. |
| GET | `/api/v1/downloads/{id}` | One job. |
| DELETE | `/api/v1/queue/{id}` | Remove a waiting job; 204. |
| POST | `/api/v1/downloads/{id}/cancel` | Cancel the active job; 202. |
| DELETE | `/api/v1/history/{id}` | Remove a history row; 204. |
| DELETE | `/api/v1/history` | Body `{"confirm":true}`; never deletes MP3 files. |
| GET | `/api/v1/events` | SSE events and 20-second heartbeat comments. |

SSE event names are `status`, `queue_changed`, `job_updated`, `job_completed`, `job_failed`, and `history_changed`.

Stable codes include `invalid_url`, `unsupported_host`, `duplicate_job`, `queue_full`, `job_not_found`, `job_not_cancellable`, `metadata_failed`, `download_failed`, `conversion_failed`, `storage_unavailable`, `output_path_invalid`, `insufficient_space`, `confirmation_required`, and `internal_error`. Tracebacks are logged, never returned.

## Supported URLs and limitations

Version 0.1 accepts HTTPS `youtube.com`/`www.youtube.com`/`m.youtube.com` watch URLs, `youtu.be` short links, and `youtube.com/shorts/...`. It rejects lookalike hosts, credentials, custom ports, playlist-only URLs, non-HTTPS schemes, file/local URLs, arbitrary downloader options, output templates, and caller-selected paths.

No cookies, YouTube login, Premium account support, playlists, parallel downloads, DRM circumvention, or Home Assistant entity integration is included. Private, login-required, region-blocked, age-gated, removed, or unavailable content may fail.

## Logs and troubleshooting

The App Logs tab records startup/version/non-secret configuration, job IDs/video IDs, state completion, cancellation, failures, and cleanup. Per-percent logs are not emitted.

- `output_path_invalid`: select a child folder of `/media`, preferably `youtube_audio`.
- `storage_unavailable`: check the media mount and available disk space.
- `insufficient_space`: free enough room for source, encoded MP3, cover, and temporary overhead.
- `metadata_failed`/`download_failed`: confirm availability without login and update to a release with current `yt-dlp`.
- `conversion_failed`: attach the App log and diagnostics to an issue, removing private metadata first.
- 502 Ingress: wait for `/api/health`; if it persists, review startup logs.

## Updates

The image contains pinned Python/frontend dependencies, `yt-dlp`, ffmpeg, and the compiled UI. Dependabot proposes updates; CI must pass before a tagged release publishes GHCR manifests. Runtime self-modification is intentionally prohibited.

## Backup and restore

The App uses `backup: cold`, so Supervisor stops it while backing up its `/data` area. `/data` contains `options.json`, SQLite state, and temporary work. Final MP3s live in shared `/media`, which may not be part of an App-only backup. Back up that library separately according to your Home Assistant storage plan.

For a restore, stop the App, restore the App backup through Home Assistant, restore `/media` separately if required, verify Configuration, then start. Do not replace an open SQLite database manually.

## Privacy and legal notice

No analytics or external project service is used. The source URL and network requests required for extraction/download go to YouTube and its delivery hosts. History remains in local App storage until trimmed or deleted.

This application is intended only for content that the user is legally authorized to download and convert. Users are responsible for applicable law, copyright, licenses, and source-service terms. A paid subscription does not by itself establish export rights.
