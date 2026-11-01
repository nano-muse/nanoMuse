import { describe, expect, it } from "vitest";
import { keptShown } from "./primitives";

// a poll hands the table a fresh array of the same rows: an expanded "More" must
// survive it, and give way only when the list itself no longer reaches what was shown

describe("keptShown", () => {
  it("keeps an expansion across a poll of the same or a longer list", () => {
    expect(keptShown(200, 100, 140)).toBe(140); // the list shrank below the expansion
    expect(keptShown(200, 100, 260)).toBe(200); // the list still reaches it
    expect(keptShown(200, 100, 200)).toBe(200);
  });

  it("never shows past the limit a fresh table starts from", () => {
    expect(keptShown(100, 100, 500)).toBe(100); // unexpanded stays at the limit
    expect(keptShown(150, 100, 30)).toBe(100); // a much shorter list falls back to it
  });
});
