import { describe, expect, it } from "vitest";
import { platformOf } from "./client";

// the relay's client.py reads these tokens; the console reads them the same way, or a
// session's user agent falls to "other" on every page that classifies client-side

describe("platformOf", () => {
  it("reads the product tokens the apps sign with", () => {
    expect(platformOf("nanoMuse-Android/1.0.9")).toBe("android");
    expect(platformOf("nanoMuse-iOS/1.0.9")).toBe("ios");
    expect(platformOf("deepseek-harness 2.3 nanoMuse/1.0.9 (windows)")).toBe("desktop");
    expect(platformOf("Minis/0.4.1")).toBe("minis");
  });

  it("reads a legacy runtime's SDK user agent the way the relay reads it", () => {
    expect(platformOf("AsyncOpenAI/Python 3.11.0")).toBe("runtime");
  });

  it("reads the bracketed system out of a runtime's own string", () => {
    expect(platformOf("nanoMuse/1.0.6 (iOS 26.1; iPhone)")).toBe("ios");
    expect(platformOf("nanoMuse/1.0.9 (Windows NT 10.0)")).toBe("windows");
  });

  it("leaves browsers and unknown strings where they belong", () => {
    expect(platformOf("Mozilla/5.0 (Windows NT 10.0) Chrome/130")).toBe("browser");
    expect(platformOf("curl/8.0")).toBe("other");
    expect(platformOf("")).toBe("other");
  });
});
