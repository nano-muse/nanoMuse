import { describe, expect, it } from "vitest";
import { sameDraft } from "./drafts";

// the settings page's drafts are reseeded from its polls; a poll that changed
// nothing (a fresh object, identical values) must not touch what the operator
// is typing

describe("sameDraft", () => {
  it("sees through a poll's fresh object identity", () => {
    const seeded = { values: { allowance: 10, bonus: 5 }, version: 3 };
    const same = { values: { allowance: 10, bonus: 5 }, version: 3 };
    expect(same).not.toBe(seeded);
    expect(sameDraft(seeded, same)).toBe(true);
  });

  it("notices a value that actually moved", () => {
    expect(sameDraft({ allowance: 10 }, { allowance: 20 })).toBe(false);
    expect(sameDraft([10, 5], [10, 6])).toBe(false);
    expect(sameDraft({ version: 3 }, { version: 4 })).toBe(false);
  });
});
