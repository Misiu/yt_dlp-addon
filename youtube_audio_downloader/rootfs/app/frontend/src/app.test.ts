// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import axe from "axe-core";

const api = vi.hoisted(() => ({
  request: vi.fn(),
  apiUrl: vi.fn(() => new URL("http://localhost/api/v1/events")),
}));

vi.mock("./api", () => ({
  ApiError: class ApiError extends Error {},
  apiUrl: api.apiUrl,
  request: api.request,
}));

const eventSources: FakeEventSource[] = [];

class FakeEventSource extends EventTarget {
  onerror: (() => void) | null = null;
  onopen: (() => void) | null = null;
  constructor() {
    super();
    eventSources.push(this);
  }
  close(): void {}
}

vi.stubGlobal("EventSource", FakeEventSource);

import "./app";

const currentJob = {
  id: "f8e338df-2a26-4651-9104-a0975944134f",
  url: "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  video_id: "dQw4w9WgXcQ",
  state: "downloading",
  created_at: "2026-07-17T08:00:00Z",
  started_at: "2026-07-17T08:00:01Z",
  finished_at: null,
  title: "Example audio",
  channel: "Example channel",
  thumbnail_url: null,
  progress: 42,
  downloaded_bytes: 4_200_000,
  total_bytes: 10_000_000,
  speed_bytes_per_second: 1_000_000,
  eta_seconds: 6,
  output_file: null,
  file_size: null,
  error_code: null,
  error_message: null,
  warning_message: null,
} as const;

function mockApi(): void {
  api.request.mockImplementation((path: string, options?: RequestInit) => {
    if (path === "v1/status")
      return Promise.resolve({ state: "downloading", progress: 42, queue_length: 1, current: currentJob });
    if (path === "v1/queue") return Promise.resolve({ items: [{ ...currentJob, id: "queued", state: "queued" }] });
    if (path.startsWith("v1/history")) return Promise.resolve({ items: [{ ...currentJob, id: "done", state: "completed", finished_at: "2026-07-17T08:02:00Z", output_file: "youtube_audio/Example audio.mp3", file_size: 5000000 }], page: 1, page_size: 25, total: 1 });
    if (path === "v1/info") return Promise.resolve({ version: "0.1.4", api_version: 1, instance_id: "7ca8ca91-d0bd-4a99-af59-7ff59cc2be42", yt_dlp_version: "2026.7.4", ffmpeg_version: "installed", architecture: "amd64", output_directory: "youtube_audio", database: "/data/youtube_audio.db", queue_limit: 100 });
    if (path === "v1/downloads/batch" && options?.method === "POST") return Promise.resolve({ accepted: 1, items: [{ id: "new", state: "queued" }] });
    return Promise.resolve(undefined);
  });
}

async function renderApp(): Promise<HTMLElement> {
  const element = document.createElement("youtube-audio-app") as HTMLElement & { updateComplete: Promise<boolean> };
  document.body.append(element);
  await element.updateComplete;
  await new Promise((resolve) => setTimeout(resolve, 0));
  await element.updateComplete;
  return element;
}

beforeEach(() => { api.request.mockReset(); mockApi(); });
afterEach(() => { document.body.replaceChildren(); vi.clearAllTimers(); });

describe("youtube-audio-app", () => {
  it("renders current work, queue, history, and diagnostics", async () => {
    const element = await renderApp();
    const content = element.shadowRoot?.textContent ?? "";
    expect(content).toContain("Example audio");
    expect(content).toContain("Example channel");
    expect(content).toContain("youtube_audio/Example audio.mp3");
    expect(content).toContain("2026.7.4");
    expect(element.shadowRoot?.querySelector("wa-progress-bar")?.getAttribute("value")).toBe("42");
  });

  it("applies live progress from the SSE job payload", async () => {
    const element = await renderApp();
    eventSources.at(-1)?.dispatchEvent(new MessageEvent("job_updated", {
      data: JSON.stringify({
        job: {
          ...currentJob,
          progress: 72.8,
          downloaded_bytes: 7_280_000,
          eta_seconds: 2,
        },
      }),
    }));
    await (element as HTMLElement & { updateComplete: Promise<boolean> }).updateComplete;

    expect(element.shadowRoot?.querySelector("wa-progress-bar")?.getAttribute("value")).toBe("72.8");
    expect(element.shadowRoot?.querySelector(".current-state")?.textContent).toBe("Downloading");
  });

  it("validates and submits multiple URLs with the stable batch request shape", async () => {
    const element = await renderApp();
    const input = element.shadowRoot?.querySelector("wa-textarea") as HTMLElement & { value: string };
    input.value = "https://youtu.be/dQw4w9WgXcQ\nhttps://youtube.com/shorts/9bZkp7q19f0";
    input.dispatchEvent(new Event("input", { bubbles: true, composed: true }));
    element.shadowRoot?.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(api.request).toHaveBeenCalledWith(
      "v1/downloads/batch",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ urls: ["https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://www.youtube.com/watch?v=9bZkp7q19f0"] }) }),
    );
  });

  it("provides labelled controls and live status semantics", async () => {
    const element = await renderApp();
    expect(element.shadowRoot?.querySelector('wa-button[aria-label="Refresh"]')).not.toBeNull();
    expect(element.shadowRoot?.querySelector("[aria-live=polite]")).not.toBeNull();
    expect(element.shadowRoot?.querySelector("wa-progress-bar")?.getAttribute("aria-valuenow")).toBe("42");
    expect(element.shadowRoot?.querySelector("dialog[aria-labelledby=clear-title]")).not.toBeNull();
    document.documentElement.lang = "en";
    document.title = "YouTube Audio Downloader";
    const audit = await axe.run(document, { rules: { "color-contrast": { enabled: false } } });
    expect(audit.violations).toEqual([]);
  });
});
