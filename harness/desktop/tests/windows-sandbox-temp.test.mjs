import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtemp, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { probeWindowsSandboxTemp, windowsSandboxTempEnvironment } from "../out/windows-sandbox-temp.js";

function setup(overrides = {}) {
  const calls = [];
  const logs = [];
  const options = {
    platform: "win32", env: { TEMP: "D:\\Temp", TMP: "D:\\Temp", KEEP: "yes" },
    inheritedRoot: "D:\\Temp", fallbackRoots: ["C:\\Users\\test\\AppData\\Local\\nanoMuse\\sandbox-temp"],
    probe: async (...args) => { calls.push(args); return { ok: true }; },
    log: (line) => logs.push(line), ...overrides,
  };
  return { options, calls, logs };
}

test("non-Windows hosts never probe or change their environment", async () => {
  const { options, calls } = setup({ platform: "linux" });
  assert.equal(await windowsSandboxTempEnvironment(options), options.env);
  assert.deepEqual(calls, []);
});

test("an inherited temp directory that accepts Low labels is retained", async () => {
  const { options, calls } = setup();
  assert.equal(await windowsSandboxTempEnvironment(options), options.env);
  assert.deepEqual(calls, [["D:\\Temp", false]]);
});

test("a denied Low label selects a tested fallback and changes only child temp variables", async () => {
  const calls = [];
  const { options, logs } = setup({
    env: { TEMP: "D:\\Temp", Temp: "D:\\Temp", tmp: "D:\\Temp", TMPDIR: "D:\\Temp", KEEP: "yes" },
    probe: async (...args) => {
      calls.push(args);
      return args[0] === "D:\\Temp" ? { ok: false, stage: "label", code: "5" } : { ok: true };
    },
  });
  const original = { ...options.env };
  const result = await windowsSandboxTempEnvironment(options);
  assert.deepEqual(result, { TEMP: options.fallbackRoots[0], TMP: options.fallbackRoots[0], TMPDIR: options.fallbackRoots[0], KEEP: "yes" });
  assert.deepEqual(options.env, original);
  assert.deepEqual(calls, [["D:\\Temp", false], [options.fallbackRoots[0], true]]);
  assert.match(logs[0], /D:.*stage=label, code=5/);
});

test("failure of every candidate preserves the environment and explains the blocked sandbox", async () => {
  const { options, logs } = setup({ probe: async () => ({ ok: false, stage: "label", code: "timeout", cleanupCode: "EACCES" }) });
  assert.equal(await windowsSandboxTempEnvironment(options), options.env);
  assert.match(logs[0], /stage=label, code=timeout, cleanup=EACCES/);
  assert.match(logs.at(-1), /fully quit and restart/);
  assert.match(logs.at(-1), /restrictions remain enabled/);
});

test("relative paths are refused and duplicate Windows paths are not probed again", async () => {
  const calls = [];
  const { options } = setup({
    inheritedRoot: "relative", fallbackRoots: ["\\Temp", "D:\\Temp", "d:/temp/", "C:\\Temp"],
    probe: async (...args) => { calls.push(args); return { ok: false, stage: "create", code: "EACCES" }; },
  });
  await windowsSandboxTempEnvironment(options);
  assert.deepEqual(calls, [["D:\\Temp", true], ["C:\\Temp", true]]);
});

test("the probe labels only a fresh empty child and removes it after success or failure", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "nanomuse-temp-test-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  await writeFile(join(root, "untouched.txt"), "keep");
  for (const denied of [false, true]) {
    const result = await probeWindowsSandboxTemp(root, false, async (directory) => {
      assert.notEqual(directory, root);
      assert.equal(directory.startsWith(join(root, "nanomuse-acl-probe-")), true);
      assert.deepEqual(await readdir(directory), []);
      if (denied) throw Object.assign(new Error("label denied"), { code: 5 });
    });
    assert.deepEqual(result, denied ? { ok: false, stage: "label", code: "5" } : { ok: true });
    assert.deepEqual(await readdir(root), ["untouched.txt"]);
  }
});

test("an absent inherited root is not created, but a fallback root can be created", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "nanomuse-temp-test-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const absent = join(root, "app", "temp");
  assert.deepEqual(await probeWindowsSandboxTemp(absent, false, async () => {}), { ok: false, stage: "create", code: "ENOENT" });
  assert.deepEqual(await probeWindowsSandboxTemp(absent, true, async () => {}), { ok: true });
  assert.deepEqual(await readdir(absent), []);
});

test("a probe that cannot be cleaned is rejected, preserving the original label error", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "nanomuse-temp-test-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  for (const denied of [false, true]) {
    const result = await probeWindowsSandboxTemp(root, false, async (directory) => {
      // Do not recursively remove unexpected contents from a probe directory.
      await writeFile(join(directory, "unexpected.txt"), "keep");
      if (denied) throw Object.assign(new Error("label denied"), { code: 5 });
    });
    assert.equal(result.ok, false);
    assert.equal(result.stage, denied ? "label" : "cleanup");
    if (denied) {
      assert.equal(result.code, "5");
      assert.equal(typeof result.cleanupCode, "string");
    }
  }
});

test("Windows can label and clean a real temporary probe", { skip: process.platform !== "win32" }, async (t) => {
  const root = await mkdtemp(join(tmpdir(), "nanomuse-temp-native-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  assert.deepEqual(await probeWindowsSandboxTemp(root, false), { ok: true });
  assert.deepEqual(await readdir(root), []);
});
