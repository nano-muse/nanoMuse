import { describe, expect, it } from "vitest";
import { liveWorking, WORKING_TTL_MS } from "./presence";
import { looksLikeForeignNumber } from "./region";

// Main first (contract C9): the "{device} is working…" line and the sign-in hint

describe("liveWorking", () => {
  const now = Date.UTC(2026, 9, 5, 12);
  const entry = (thread: string, agoMs: number) => ({ thread, cid: `c-${thread}`, device: "d1", device_name: "kwai", at: (now - agoMs) / 1000 });

  it("keeps entries younger than ten minutes, by thread", () => {
    const out = liveWorking([entry("main", 1000), entry("side", WORKING_TTL_MS - 1000)], now);
    expect(Object.keys(out).sort()).toEqual(["main", "side"]);
    expect(out.main?.device_name).toBe("kwai");
  });

  it("drops entries that are ten minutes old or older", () => {
    const out = liveWorking([entry("main", WORKING_TTL_MS), entry("side", WORKING_TTL_MS * 3)], now);
    expect(out).toEqual({});
  });

  it("takes an absent list as nobody working", () => {
    expect(liveWorking(undefined, now)).toEqual({});
  });
});

describe("looksLikeForeignNumber", () => {
  it("spots a country code other than +86", () => {
    expect(looksLikeForeignNumber("+1 415 555 0100")).toBe(true);
    expect(looksLikeForeignNumber("0044 20 7946 0000")).toBe(true);
  });

  it("leaves mainland numbers and e-mail addresses alone", () => {
    expect(looksLikeForeignNumber("+86 138 0000 0000")).toBe(false);
    expect(looksLikeForeignNumber("+8613800138000")).toBe(false); // E.164, no spaces
    expect(looksLikeForeignNumber("0086 138 0000 0000")).toBe(false);
    expect(looksLikeForeignNumber("138 0000 0000")).toBe(false);
    expect(looksLikeForeignNumber("you@example.com")).toBe(false);
  });
});
