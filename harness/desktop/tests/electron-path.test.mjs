import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { electronPath } from "../scripts/electron-path.mjs";

function fixture(t, folder) {
  const parent = resolve(tmpdir());
  const root = mkdtempSync(join(parent, "nanomuse-electron-path-"));
  t.after(() => {
    assert.equal(dirname(resolve(root)), parent);
    assert.ok(root.startsWith(join(parent, "nanomuse-electron-path-")));
    rmSync(root, { recursive: true, force: true });
  });
  const dir = join(root, folder);
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "package.json"), '{"type":"commonjs"}\n');
  writeFileSync(join(dir, "index.js"), 'module.exports = "electron-fixture";\n');
  return dir;
}

test("Electron's CommonJS package supplies its executable path", async (t) => {
  assert.equal(await electronPath(fixture(t, "electron")), "electron-fixture");
});

test("the package path can contain spaces, Unicode, hash and percent characters", async (t) => {
  assert.equal(await electronPath(fixture(t, "electron path # % 测试")), "electron-fixture");
});

test("a missing Electron package leaves error handling to the caller", async (t) => {
  const dir = fixture(t, "electron");
  await assert.rejects(electronPath(join(dir, "missing")), { code: "ERR_MODULE_NOT_FOUND" });
});
