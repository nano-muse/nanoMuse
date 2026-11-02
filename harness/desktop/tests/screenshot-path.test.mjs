import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import { nextScreenshotPath } from "../out/screenshot-path.js";

test("two report screenshots inside one second are two files", (t) => {
  const dir = mkdtempSync(join(tmpdir(), "nm-shot-"));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const stamp = "2026-11-02T19-10-40";
  const first = nextScreenshotPath(dir, stamp);
  writeFileSync(first, "one");
  const second = nextScreenshotPath(dir, stamp);
  assert.notEqual(second, first);
  assert.equal(second.endsWith("-2.png"), true);
  writeFileSync(second, "two");
  assert.equal(nextScreenshotPath(dir, stamp).endsWith("-3.png"), true);
});

test("a lone report screenshot keeps the plain name", (t) => {
  const dir = mkdtempSync(join(tmpdir(), "nm-shot-"));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  assert.equal(nextScreenshotPath(dir, "2026-11-02T19-10-41"), join(dir, "nanoMuse-2026-11-02T19-10-41.png"));
});
