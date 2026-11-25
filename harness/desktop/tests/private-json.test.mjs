import assert from "node:assert/strict";
import { chmod, mkdtemp, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { readPrivateJson, writePrivateJson } from "../out/private-json.js";

test("private JSON is replaced atomically and keeps a recoverable private backup", async () => {
  const dir = await mkdtemp(join(tmpdir(), "nm-private-json-"));
  const path = join(dir, "desktop.json");
  try {
    writePrivateJson(path, { proxy: "http://user:pass@proxy.example" });
    writePrivateJson(path, { menuBar: false });
    assert.deepEqual(JSON.parse(await readFile(path, "utf8")), { menuBar: false });
    assert.deepEqual(JSON.parse(await readFile(`${path}.bak`, "utf8")), { proxy: "http://user:pass@proxy.example" });
    if (process.platform !== "win32") {
      assert.equal((await stat(path)).mode & 0o777, 0o600);
      assert.equal((await stat(`${path}.bak`)).mode & 0o777, 0o600);
    }
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("a partial or damaged current file is restored from the last complete backup", async () => {
  const dir = await mkdtemp(join(tmpdir(), "nm-private-json-"));
  const path = join(dir, "desktop.json");
  try {
    await writeFile(`${path}.bak`, '{"menuBar":true}\n', { mode: 0o644 });
    await writeFile(path, '{"menu', { mode: 0o644 });
    const value = readPrivateJson(path, (raw) => raw && typeof raw === "object" ? raw : undefined);
    assert.deepEqual(value, { menuBar: true });
    assert.deepEqual(JSON.parse(await readFile(path, "utf8")), { menuBar: true });
    assert.deepEqual(JSON.parse(await readFile(`${path}.bak`, "utf8")), { menuBar: true });
    assert.deepEqual((await readdir(dir)).sort(), ["desktop.json", "desktop.json.bak"]);
    if (process.platform !== "win32") {
      assert.equal((await stat(path)).mode & 0o777, 0o600);
      assert.equal((await stat(`${path}.bak`)).mode & 0o777, 0o600);
    }
  } finally {
    await chmod(dir, 0o700).catch(() => undefined);
    await rm(dir, { recursive: true, force: true });
  }
});
