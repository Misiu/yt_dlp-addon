# Companion Home Assistant integration contract

This document is the implementation brief for a separate HACS custom-integration repository. The integration domain and Supervisor discovery service are both `youtube_audio_downloader`.

## Discovery and connection

The App declares:

```yaml
discovery:
  - youtube_audio_downloader
```

At startup, after transient failures, and once per day, it sends this shape to `POST http://supervisor/discovery` using its `SUPERVISOR_TOKEN`:

```json
{
  "service": "youtube_audio_downloader",
  "config": {
    "host": "<App container hostname>",
    "port": 8099,
    "auth_token": "<dedicated bearer token>",
    "instance_id": "<stable UUID>",
    "api_version": 1
  }
}
```

The port is internal to the Home Assistant container network. It is not a host-port mapping and is not configurable by the user. Build the base URL as `http://{host}:{port}`. Send `Authorization: Bearer {auth_token}` on every HTTP and SSE request. Never log the token or source video URLs.

The App stores `instance_id` and `auth_token` in `/data/integration_credentials.json`. Both remain stable across restarts and updates. If App data is removed, the new App installation has a new identity and token.

## Stable API v1

Required endpoints:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Connectivity and App version. |
| GET | `/api/v1/info` | Includes `version`, `api_version`, `instance_id`, architecture, output directory, and queue limit. |
| GET | `/api/v1/status` | Overall state, queue length, and current job. |
| GET | `/api/v1/queue` | Waiting and active jobs. |
| GET | `/api/v1/history?page=1&page_size=25` | Terminal history. |
| POST | `/api/v1/downloads` | Queue one URL with `{"url":"https://..."}`. Returns HTTP 202 and `{id,state}`. |
| POST | `/api/v1/downloads/batch` | Atomically queue 1–50 URLs with `{"urls":[...]}`. |
| POST | `/api/v1/downloads/{id}/cancel` | Cancel the active job. |
| POST | `/api/v1/history/{id}/redownload` | With `{"confirm":true}`, queue a history source again and force destination replacement. |
| GET | `/api/v1/events` | Named Server-Sent Events with heartbeat comments. |

API error bodies are always `{"error":{"code":"...","message":"..."}}`. HTTP 401 means the integration token is missing or invalid. Validation and queue conflicts use HTTP 4xx; transport/server failures use standard HTTP 5xx.

SSE event names are `status`, `queue_changed`, `job_updated`, `job_completed`, `job_failed`, and `history_changed`. Job events contain `{"job": <full Job object>}`. Use REST for the initial snapshot and reconciliation, then SSE for immediate updates. Reconnect SSE with bounded exponential backoff and refresh the REST snapshot after reconnecting.

The Job object includes parsed `title` and `artist`, the original `source_title`, source `channel`/`uploader`, thumbnail URL, progress metrics, state, timestamps, output path, warnings, and structured error fields. Prefer `artist` over `channel` when presenting track metadata.

## Custom integration requirements

Create a separate repository suitable for HACS, preferably named `yt_dlp-integration`, containing `custom_components/youtube_audio_downloader`.

The manifest should use:

- `domain`: `youtube_audio_downloader`;
- `integration_type`: `service`;
- `iot_class`: `local_push`;
- `config_flow`: `true`;
- `single_config_entry`: `true`;
- a minimum supported Home Assistant version chosen from the version used by CI.

Implement `async_step_hassio(discovery_info: HassioServiceInfo)`. Validate the required discovery fields and `api_version == 1`, call the authenticated info endpoint, set the config-entry unique ID to `instance_id`, and always show a confirmation step before creating a new entry. On rediscovery, update host, port, and token for the matching instance and reload an existing entry when needed. A manually initiated user flow should explain that the App must be installed and running; users must never be asked to retrieve the generated token themselves.

Use Home Assistant's shared `aiohttp` client session. Keep API access in a small typed client module and keep the config entry's runtime objects in `ConfigEntry.runtime_data`. Shut down the SSE task and HTTP response cleanly on unload.

## Required actions

Register actions once in the integration's top-level `async_setup`, not per config entry:

1. `youtube_audio_downloader.download`
   - required string field `url`;
   - calls `POST /api/v1/downloads`;
   - suitable for the visual automation editor and YAML.
2. `youtube_audio_downloader.download_batch`
   - required list field `urls`, 1–50 strings;
   - calls `POST /api/v1/downloads/batch`.

Provide `services.yaml`, English and Polish translations, URL selectors/text selectors where supported, and actionable `ServiceValidationError` messages mapped from App error codes. The App remains the source of truth for URL validation.

Example automation target:

```yaml
actions:
  - action: youtube_audio_downloader.download
    data:
      url: "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

## Entities

Represent one Home Assistant service device identified by `(DOMAIN, instance_id)`, with App version as `sw_version`. At minimum expose:

- queue length sensor;
- current state sensor;
- current download progress sensor in percent.

Entities should become unavailable on connection loss and update from the shared REST/SSE coordinator. Do not duplicate the Supervisor-provided App update entity.

## Tests and release quality

Cover discovery confirmation, rediscovery updates, invalid API versions, authentication failure, action registration and payloads, App error mapping, REST snapshot updates, SSE updates/reconnect, unload cleanup, entity availability, translations, and HACS validation. CI should run Ruff, mypy, pytest with Home Assistant test helpers, Hassfest where applicable, and HACS validation. Do not include personal data, real media titles, private URLs, tokens, or local paths in fixtures and logs.
