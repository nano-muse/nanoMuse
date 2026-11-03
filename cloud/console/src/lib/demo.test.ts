import { describe, expect, it } from "vitest";
import { perDayVisits } from "./demo";

// a running visit sits in both the active and the recent list; the page's own
// table counts it once, and so must the chart beside it

const now = 1_900_000_000; // offset 0: day start is a fixed boundary below
const started = now - 60; // a minute ago, inside today's bucket

describe("perDayVisits", () => {
  it("counts a visit that is both active and recent once", () => {
    const visit = { id: "v1", started, ended: 0 } as never;
    const { per } = perDayVisits([visit], [visit], 7, 0, now);
    const total = per.reduce((a, b) => a + b, 0);
    expect(total).toBe(1);
  });

  it("counts a visit in only one of the lists once", () => {
    const ended = { id: "v2", started, ended: started + 1 } as never;
    const running = { id: "v3", started: now - 30, ended: 0 } as never;
    const { per } = perDayVisits([running], [ended], 7, 0, now);
    expect(per.reduce((a, b) => a + b, 0)).toBe(2);
  });

  it("puts visits on opposite sides of the site's midnight in different buckets", () => {
    const midnight = Date.UTC(2026, 9, 31, 16) / 1000; // Nov 1 at UTC+8
    const { per, start } = perDayVisits([], [
      { id: "before", started: midnight - 1, ended: 1 } as never,
      { id: "after", started: midnight + 1, ended: 1 } as never,
    ], 2, 8, midnight + 3600);
    expect(start).toBe(midnight - 86400);
    expect(per).toEqual([1, 1]);
  });
});
