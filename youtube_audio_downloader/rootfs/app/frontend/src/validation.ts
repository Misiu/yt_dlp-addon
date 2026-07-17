const VIDEO_ID = /^[A-Za-z0-9_-]{6,20}$/;
const WATCH_HOSTS = new Set(["youtube.com", "www.youtube.com", "m.youtube.com"]);
const SHORT_HOSTS = new Set(["youtu.be", "www.youtu.be"]);

export function canonicalYouTubeUrl(value: string): string | null {
  if (value.length > 2048) return null;
  const authority = value.startsWith("https://")
    ? (value.slice(8).split(/[/?#]/, 1)[0] ?? "")
    : "";
  if (authority.includes(":")) return null;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  if (url.protocol !== "https:" || url.username || url.password || url.port) return null;
  const host = url.hostname.toLowerCase().replace(/\.$/, "");
  let videoId: string | null = null;
  if (SHORT_HOSTS.has(host)) {
    videoId = url.pathname.replace(/^\/+|\/+$/g, "").split("/", 1)[0] || null;
  } else if (WATCH_HOSTS.has(host)) {
    const path = url.pathname.replace(/\/+$/, "");
    if (path === "/watch") videoId = url.searchParams.get("v");
    else if (path.startsWith("/shorts/") || path.startsWith("/embed/"))
      videoId = path.split("/", 3)[2] || null;
  }
  return videoId && VIDEO_ID.test(videoId)
    ? `https://www.youtube.com/watch?v=${videoId}`
    : null;
}

export function parseYouTubeUrlLines(value: string): string[] | null {
  const lines = value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length === 0 || lines.length > 50) return null;
  const canonical = lines.map(canonicalYouTubeUrl);
  if (canonical.some((url) => url === null)) return null;
  const urls = canonical as string[];
  return new Set(urls).size === urls.length ? urls : null;
}
