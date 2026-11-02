import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { once } from "node:events";
import { mkdir, mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";

function assertRetained(actual, expected) {
  if (Array.isArray(expected)) {
    assert.equal(actual.length, expected.length);
    expected.forEach((value, index) => assertRetained(actual[index], value));
  } else if (expected && typeof expected === "object") {
    for (const [key, value] of Object.entries(expected)) assertRetained(actual[key], value);
  } else assert.deepEqual(actual, expected);
}

async function stop(child) {
  if (!child.pid || child.exitCode !== null || child.signalCode !== null) return;
  const exited = once(child, "exit");
  if (process.platform === "win32") spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore" });
  else child.kill("SIGTERM");
  const timer = setTimeout(() => child.kill("SIGKILL"), 3000);
  try {
    await exited;
  } finally {
    clearTimeout(timer);
  }
}

export async function checkSavedProfileStartup(electron, dshDir) {
  const require = createRequire(join(dshDir, "package.json"));
  const { parse } = require("yaml");
  const home = await mkdtemp(join(tmpdir(), "nanomuse-saved-profile-"));
  const profile = join(home, "profiles", "nanomuse");
  const patchPath = join(profile, "cordis.patch.yml");
  const traps = [];
  let staleRequests = 0;
  const trap = async (port = 0) => {
    const server = createServer((request, response) => {
      staleRequests += 1;
      response.writeHead(500).end("stale provider address");
    });
    server.listen(port, "127.0.0.1");
    await once(server, "listening");
    traps.push(server);
    return `http://127.0.0.1:${server.address().port}/v1`;
  };
  try {
    let previousBase = await trap();
    const cloud = { displayName: "nanoMuse Cloud", api: "openai-completions", baseURL: previousBase, apiKeyEnv: "NANOMUSE_TEST_UNUSED", models: [{ id: "test-model" }] };
    const custom = { ...cloud, displayName: "Custom", models: [{ id: "custom-model" }] };
    await mkdir(join(profile, "node_modules"), { recursive: true });
    await mkdir(join(home, "nanomuse"), { recursive: true });
    await writeFile(join(home, "nanomuse", "cloud.json"), JSON.stringify({ deviceId: "pc-dsh-test", update: { checkedAt: Date.now() } }));
    await writeFile(join(profile, "package.json"), JSON.stringify({ name: "dsh-profile-nanomuse", private: true, dependencies: { "dsh-nanomuse": "*" }, dsh: { profile: { bundles: ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app", "@deepseek-ai/dsh-experimental-schedule-bundle", "dsh-nanomuse"] } } }));
    await writeFile(join(profile, "cordis.yml"), "[]\n");
    await writeFile(patchPath, JSON.stringify([{ id: "llm-pi-ai", name: "@deepseek-ai/dsh-llm-pi-ai", config: { providers: { nanomuse: cloud, custom } } }]));
    await writeFile(join(home, "preserved.json"), '{"keep":true}\n');
    await symlink(join(dshDir, "node_modules", "dsh-nanomuse"), join(profile, "node_modules", "dsh-nanomuse"), process.platform === "win32" ? "junction" : "dir");
    let savedProviders;
    for (const launch of [1, 2]) {
      const child = spawn(electron, ["--expose-internals", join(dshDir, "node_modules", "@deepseek-ai", "dsh", "lib", "bin.js"), "nanomuse", "--no-open", "--port", "0"], {
        env: { ...process.env, ELECTRON_RUN_AS_NODE: "1", DSH_HOME: home, ELECTRON_NO_ATTACH_CONSOLE: "1" },
        stdio: ["ignore", "pipe", "pipe"],
      });
      let output = "";
      let errors = "";
      let spawnError;
      child.on("error", error => { spawnError = error; });
      child.stdout.on("data", chunk => { output += chunk; });
      child.stderr.on("data", chunk => { errors += chunk; });
      try {
        const deadline = Date.now() + 120_000;
        let url;
        let providers;
        while (Date.now() < deadline) {
          if (spawnError) throw spawnError;
          if (child.exitCode !== null || child.signalCode !== null) throw new Error(`saved-profile Host exited before readiness (${child.exitCode ?? child.signalCode})`);
          url = /dsh web: (http:\/\/127\.0\.0\.1:\d+\/\?token=\S+)/.exec(output)?.[1];
          providers = parse(await readFile(patchPath, "utf8")).find(row => row.id === "llm-pi-ai")?.config?.providers;
          if (url && providers?.nanomuse?.baseURL !== previousBase) break;
          await delay(25);
        }
        assert.ok(url, "the saved profile must announce its web address");
        assert.ok(providers?.nanomuse?.baseURL && providers.nanomuse.baseURL !== previousBase, "the saved provider must be repointed");
        assertRetained(providers.nanomuse, { ...cloud, baseURL: providers.nanomuse.baseURL });
        assertRetained(providers.custom, custom);
        if (savedProviders) assert.deepEqual(providers, { ...savedProviders, nanomuse: { ...savedProviders.nanomuse, baseURL: providers.nanomuse.baseURL } });
        savedProviders = providers;
        assert.equal(await readFile(join(home, "preserved.json"), "utf8"), '{"keep":true}\n');
        const entry = await fetch(url, { redirect: "manual", signal: AbortSignal.timeout(5000) });
        assert.equal(entry.status, 303);
        const cookie = entry.headers.getSetCookie().map(value => value.split(";")[0]).join("; ");
        for (const path of ["/nanomuse/cloud/status", "/nanomuse/rooms/state"]) {
          const response = await fetch(new URL(path, url), { headers: { cookie, "x-nanomuse": "1", "sec-fetch-site": "same-origin" }, signal: AbortSignal.timeout(5000) });
          assert.equal(response.status, 200, path);
        }
        assert.equal(staleRequests, 0);
        previousBase = providers.nanomuse.baseURL;
        console.log(`saved profile: launch ${launch} ready, provider repointed, custom settings preserved`);
      } catch (error) {
        console.error((output + errors).slice(-6000).replace(/token=\S+/g, "token=…"));
        throw error;
      } finally {
        await stop(child);
      }
      if (launch === 1) await trap(Number(new URL(previousBase).port));
    }
  } finally {
    for (const server of traps) {
      server.closeAllConnections();
      await new Promise(resolve => server.close(resolve));
    }
    await rm(home, { recursive: true, force: true });
  }
}
