import { describe, expect, it } from "vitest";

import { storedValue } from "./hooks";

describe("storedValue", () => {
  it("reads a number another page wrote", () => {
    expect(storedValue("42", 30)).toBe(42);
  });

  it("falls back to the initial value when the stored text is not a number", () => {
    expect(storedValue("abc", 30)).toBe(30);
  });

  it("falls back to the initial value on an empty string, not 0", () => {
    expect(storedValue("", 30)).toBe(30);
    expect(storedValue(" \t\n", 30)).toBe(30);
    expect(storedValue("Infinity", 30)).toBe(30);
    expect(storedValue("NaN", 30)).toBe(30);
    expect(storedValue("0", 30)).toBe(0);
  });

  it("keeps booleans and strings as they were stored", () => {
    expect(storedValue("1", false)).toBe(true);
    expect(storedValue("0", true)).toBe(false);
    expect(storedValue("dark", "light")).toBe("dark");
    expect(storedValue(null, "light")).toBe("light");
  });
});
