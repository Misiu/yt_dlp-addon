import { describe, expect, it } from "vitest";
import { canonicalYouTubeUrl, parseYouTubeUrlLines } from "./validation";

describe("YouTube URL validation", () => {
  it("matches the backend allowlist and canonicalizes supported routes", () => {
    expect(canonicalYouTubeUrl("https://youtu.be/dQw4w9WgXcQ")).toBe(
      "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    );
    expect(canonicalYouTubeUrl("https://m.youtube.com/shorts/9bZkp7q19f0")).toBe(
      "https://www.youtube.com/watch?v=9bZkp7q19f0",
    );
    expect(canonicalYouTubeUrl("https://youtube.example/watch?v=dQw4w9WgXcQ")).toBeNull();
    expect(canonicalYouTubeUrl("http://youtube.com/watch?v=dQw4w9WgXcQ")).toBeNull();
  });

  it("accepts unique links line by line and rejects duplicates", () => {
    expect(
      parseYouTubeUrlLines(
        "https://youtu.be/dQw4w9WgXcQ\nhttps://youtube.com/watch?v=9bZkp7q19f0",
      ),
    ).toHaveLength(2);
    expect(
      parseYouTubeUrlLines(
        "https://youtu.be/dQw4w9WgXcQ\nhttps://youtube.com/watch?v=dQw4w9WgXcQ",
      ),
    ).toBeNull();
  });
});
