# YouTube Audio Downloader

Download audio you are authorized to use, convert it to MP3, add metadata and cover art, and save it directly to Home Assistant media storage. Open the Ingress Web UI from the App page or enable **Show in sidebar**, then paste one link or up to 50 links (one per line) into the queue form.

The App provides:

- an authenticated Ingress Web UI with a durable queue and history;
- an authenticated internal API announced automatically for a companion Home Assistant integration;
- safe single-video downloads, tagged MP3 output, cancellation, and restart recovery;
- English and Polish configuration labels;
- no elevated Home Assistant or Supervisor API privileges and no account credentials.

Final files are written below the configured `/media` directory. Job state is stored separately in `/data`. Source URLs are sent only to the source service and its media/CDN hosts as needed by `yt-dlp`; no analytics service is included.

Read the [full documentation](DOCS.md) for the internal API and storage model.

Use this App only for content you are legally authorized to download and convert.
