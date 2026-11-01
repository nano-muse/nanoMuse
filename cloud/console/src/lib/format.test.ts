import { describe, expect, it } from "vitest";
import { siteDay, siteDayStamp, siteDayStart, siteWeekday } from "./format";

// the relay's grid: a day stamp is the site-local day's start as a UNIX time, so
// 2026-10-31T16:00Z is the start of Nov 1 at the default offset of +8h
const NOV_1_AT_8 = Date.UTC(2026, 9, 31, 16) / 1000;

describe("siteDay", () => {
  it("labels a day stamp with the site's calendar date, not the browser's", () => {
    expect(siteDay(NOV_1_AT_8, 8)).toBe("2026-11-01");
    expect(siteDay(NOV_1_AT_8, 0)).toBe("2026-10-31");
  });

  it("answers the weekday at the site too", () => {
    expect(siteWeekday(NOV_1_AT_8, 8, false)).toBe("Sun"); // 2026-11-01, a Sunday at +8
    expect(siteWeekday(NOV_1_AT_8, 0, false)).toBe("Sat"); // still Oct 31 at +0
    expect(siteWeekday(NOV_1_AT_8, 8, true)).toBe("日");
  });
});

describe("siteDayStamp", () => {
  it("names the day the picked date means, wherever the browser runs", () => {
    expect(siteDayStamp("2026-11-01", 8)).toBe(NOV_1_AT_8);
    expect(siteDay(siteDayStamp("2026-11-01", 8), 8)).toBe("2026-11-01");
  });
});

describe("siteDayStart", () => {
  it("finds the start of the site-local day a time falls in", () => {
    const threePastMidnightSite = Date.UTC(2026, 9, 31, 19) / 1000; // 03:00 on Nov 1 at +8
    expect(siteDayStart(threePastMidnightSite, 8)).toBe(NOV_1_AT_8);
    expect(siteDay(siteDayStart(threePastMidnightSite, 8), 8)).toBe("2026-11-01");
  });
});
