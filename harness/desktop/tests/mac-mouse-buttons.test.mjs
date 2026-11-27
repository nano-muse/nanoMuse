// This test uses fake mouse events and an isolated temporary marker directory.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const helper = fileURLToPath(new URL("../mac/computer-use/", import.meta.url));

test("mouse releases survive failures, restarts and shutdown during gestures", (t) => {
  const available = spawnSync("swiftc", ["--version"]);
  if (available.error?.code === "ENOENT" && process.platform !== "darwin") {
    return t.skip("Swift compiler unavailable");
  }
  assert.equal(available.status, 0, String(available.error ?? available.stderr));
  const dir = mkdtempSync(join(tmpdir(), "nanomuse-mouse-test-"));
  try {
    const binary = join(dir, "mouse-test");
    const compile = spawnSync("swiftc", [
      "-warnings-as-errors", "-swift-version", "5", "Sources/MouseButtons.swift",
      "Tests/MouseButtonsTest.swift", "-o", binary,
    ], { cwd: helper, encoding: "utf8" });
    assert.equal(compile.status, 0, compile.stderr);
    const run = spawnSync(binary, [], { encoding: "utf8", timeout: 15000 });
    assert.equal(run.status, 0, String(run.error ?? run.stderr));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
