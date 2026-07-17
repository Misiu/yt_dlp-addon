import { describe, expect, it } from "vitest";
import { detectLanguage, translate } from "./i18n";

describe("i18n", () => {
  it("detects Polish and falls back to English", () => {
    expect(detectLanguage("pl-PL")).toBe("pl");
    expect(detectLanguage("de-DE")).toBe("en");
  });

  it("contains translated queue labels", () => {
    expect(translate("en", "queue")).toBe("Queue");
    expect(translate("pl", "queue")).toBe("Kolejka");
  });
});
