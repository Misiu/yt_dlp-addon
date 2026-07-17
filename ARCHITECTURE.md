# Architecture

## Scope

YouTube Audio Downloader is a Home Assistant App (formerly called an add-on) that accepts an authorized YouTube video URL, serializes it into a durable FIFO queue, and produces a tagged MP3 under Home Assistant media storage. It does not expose Home Assistant entities or require Supervisor/Core API access.

## Decisions

### Base image and process model

The runtime uses the pinned multi-architecture Home Assistant Alpine base `ghcr.io/home-assistant/base:3.23`. It supplies the supported s6-overlay v3 init and bashio environment. Python, ffmpeg, Node.js, CA certificates and all Python wheels are installed while building; the running app never installs or upgrades itself. Node.js is the external JavaScript runtime required by current yt-dlp YouTube challenge solving, and the pinned `yt-dlp[default]` dependency supplies the matching EJS scripts. `init: false` is required because the image has s6-overlay v3. s6 owns signal forwarding and process reaping, while Uvicorn owns the application lifecycle.

The service currently runs as the container user used by the Home Assistant base image. This is necessary for reliable writes to Supervisor-managed `/data` and the explicitly mapped `/media` volume across Home Assistant OS installations. It is confined by protection mode and a custom AppArmor profile to the image, `/data`, `/media`, `/tmp`, networking, and the required executables. No host network, privileged capability, device, Supervisor API, or Home Assistant API access is requested.

### Persistence and queue recovery

SQLite at `/data/youtube_audio.db` is the source of truth. A small numbered migration system creates a `jobs` table and indexes. Each mutation is committed before an event is emitted. Exactly one coroutine consumes queued rows in creation order. On startup, work that was in a transient state is returned to `queued`, annotated with `restart_requeued`, and attempted again; stale temporary files older than 24 hours are removed. Terminal history is trimmed to `history_limit`; deleting history never deletes media.

### Process isolation

Metadata extraction and download use `python -m yt_dlp` in child processes; conversion uses a separate `ffmpeg` child process. Arguments are fixed lists, never a shell string, and the API cannot provide downloader flags or output paths. The worker captures bounded output, applies timeouts, terminates children on cancellation/shutdown, and kills them if graceful termination expires. Blocking image and ID3 operations run through `asyncio.to_thread`.

### Live updates and Ingress

SSE is used because updates are server-to-client only. `ingress_stream: true` prevents response buffering, and heartbeat comments keep proxies from considering an idle stream dead. The frontend reconnects automatically and falls back to 10-second REST polling. Vite emits relative asset URLs (`base: "./"`), the UI uses a single route, and API URLs are resolved against `document.baseURI`, so no code assumes `/` is the public prefix.

The app listens on container-internal port 8099 for authenticated Ingress, but publishes no host port. A future companion integration can receive the internal host and port through Supervisor discovery and use the same versioned API without user network configuration.

### Frontend design system

The UI bundles Lit and the public `@home-assistant/webawesome` package used by the Home Assistant frontend. It does not rely on private `ha-*` elements from the parent Home Assistant document. Local semantic HTML/CSS uses Home Assistant custom-property names when Ingress supplies them and accessible fallbacks otherwise. English and Polish strings are centralized in the frontend bundle.

### Security model

Only HTTPS URLs on an exact allowlist of YouTube hosts are accepted. Video IDs are parsed structurally, playlist-only URLs are rejected, URL length is bounded, and active video IDs are unique. Thumbnail retrieval accepts only public DNS results and bounded HTTPS responses. Output configuration is normalized beneath `/media`; user input cannot alter it. Filenames remove control/path/device-name hazards while preserving Unicode. Final files are moved atomically from `/data/tmp` to `/media` after conversion and tagging.

Ingress supplies authenticated-user headers. CORS is not enabled, the API has no host mapping, and errors have stable codes without tracebacks.

### Multi-architecture and release

Only `amd64` and `aarch64`, the architectures currently documented by Home Assistant and covered by the official builder matrix, are declared. Releases use `home-assistant/builder` 2026.06 actions to publish architecture images and one generic GHCR manifest at `ghcr.io/misiu/youtube-audio-downloader:<version>`. Pull requests build both architectures without pushing.

## Corrections to the original brief

- The current example repository is `home-assistant/apps-example`; the former `addons-example` URL redirects there.
- `build.yaml` is legacy as of Supervisor 2026.04. Base images, labels, and build arguments belong in the Dockerfile.
- The current public configuration documentation lists `amd64` and `aarch64`; `armv7` is therefore not declared.
- A generic multi-architecture `image` is preferred over `{arch}` and is used here.
- App naming is used in user documentation; legacy technical redirect names such as `supervisor_add_addon_repository` remain unchanged.
