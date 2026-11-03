import { test } from "node:test";
import assert from "node:assert/strict";
import { capacityDefaultsSource } from "../scripts/capacity-defaults.mjs";

test("capacity compatibility is idempotent and refuses missing or ambiguous seams", () => {
  const source = "function profiles() {\n\t\tconst raw = config.providers.get();\n}";
  const patched = capacityDefaultsSource(source);
  assert.notEqual(patched, source);
  assert.equal(capacityDefaultsSource(patched), patched);
  assert.throws(() => capacityDefaultsSource("a changed adapter"), /seam changed/);
  assert.throws(() => capacityDefaultsSource(source + source), /seam changed/);
});
