// The helper client (src/mac-helper.ts) against a fake "nanoMuse Computer Use" — an HTTP
// server in this process that behaves like the Swift one: reads the token file the client
// wrote, writes the port file, checks the bearer token, answers the seven routes. Then the
// operator (src/operator.ts) on top of it, with a fake `electron` module in place of the
// real one, pinned to darwin: a helper whose picture fails is reported, never papered over
// with desktopCapturer. Run after `tsc -p tsconfig.json` (npm test does both). No Mac, no
// Electron needed.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, test } from "node:test";
import { MacHelper, MacHelperError, HELPER_NAME, HELPER_SCREEN_PERMISSION_TEXT, QUARANTINE_KEPT_TEXT, clearQuarantine, defaultHelperPath, describeAction, translocated } from "../out/mac-helper.js";

const roots = [];
after(() => {
  for (const dir of roots) rmSync(dir, { recursive: true, force: true });
});

// ---- a stand-in for Electron, so src/operator.ts loads under plain Node ---------------------
// `require("electron")` inside the compiled operator resolves to this object: a primary display
// of 1440×900 points at scale 2 (a Retina Mac, where the operator's space is points), a
// desktopCapturer that counts its calls and answers a grey 1440×900 frame, a nativeImage good
// enough for the black check. The operator never reaches desktopCapturer when a helper bundle
// is there — that is what the tests below show.
const electronFake = {
  captures: 0,
  clipboard: { readText: async () => "", writeText: async () => undefined },
  screen: { getPrimaryDisplay: () => ({ id: 7, size: { width: 1440, height: 900 }, scaleFactor: 2, bounds: { x: 0, y: 0, width: 1440, height: 900 } }) },
  desktopCapturer: {
    getSources: async () => {
      electronFake.captures += 1;
      return [{ display_id: "7", thumbnail: fakeImage(1440, 900) }];
    },
  },
  nativeImage: { createFromBitmap: (buffer, { width, height }) => fakeImage(width, height) },
};
function fakeImage(width, height) {
  return {
    getSize: () => ({ width, height }),
    isEmpty: () => false,
    toBitmap: () => Buffer.alloc(width * height * 4, 0x80),
    resize: ({ width: w, height: h }) => fakeImage(w, h),
    toPNG: () => Buffer.from("png-from-electron"),
    toJPEG: () => Buffer.from("jpeg-from-electron"),
  };
}
const realLoad = Module._load;
Module._load = function (request, ...rest) {
  if (request === "electron") return electronFake;
  return realLoad.call(this, request, ...rest);
};
const require = createRequire(import.meta.url);
const { Operator, OperatorError } = require("../out/operator.js");
const realPlatform = Object.getOwnPropertyDescriptor(process, "platform");
/** Run `fn` as if on a Mac (the operator reads `process.platform` on every call). */
async function onDarwin(fn) {
  Object.defineProperty(process, "platform", { value: "darwin", configurable: true });
  try {
    return await fn();
  } finally {
    Object.defineProperty(process, "platform", realPlatform);
  }
}

function scratch() {
  const dir = mkdtempSync(join(tmpdir(), "nm-mac-helper-"));
  roots.push(dir);
  return dir;
}

/** A directory that stands for the .app bundle (present() only looks for it). */
function fakeBundle(dir) {
  const app = join(dir, `${HELPER_NAME}.app`);
  mkdirSync(app, { recursive: true });
  return app;
}

/** What the Swift helper says when ScreenCaptureKit refuses: the code by name, then the system's text. */
const SCK_FAILURE = "no screenshot: ScreenCaptureKit userDeclined (-3801): The user declined TCCs for application, window, display capture";

/**
 * The fake helper: `launch` starts it the way `open` would start the real one, with the same
 * arguments. `mode` picks the behaviour: "ok", "denied" (no Screen Recording), "fails" (the
 * grant is there but ScreenCaptureKit's capture fails — a 500 with its words), "no-port"
 * (never writes the port file), "dies" (answers once, then closes).
 */
function fakeHelper(mode = "ok") {
  const state = { token: "", requests: [], servers: [], quit: 0, pid: 4242 };
  const windows = [
    { id: 41, pid: 500, app: "Safari", bundle_id: "com.apple.Safari", title: "Apple", bounds: [100, 50, 800, 600], layer: 0, on_screen: true },
    { id: 43, pid: 600, app: "Notes", bundle_id: "com.apple.Notes", title: "Shopping", bounds: [0, 0, 500, 400], layer: 0, on_screen: true },
  ];
  const launch = async (appPath, args) => {
    state.appPath = appPath;
    state.args = args;
    if (mode === "no-port") return;
    const arg = (name) => args[args.indexOf(name) + 1];
    state.token = readFileSync(arg("--token-file"), "utf8").trim();
    state.parentPid = Number(arg("--parent-pid"));
    const server = createServer((req, res) => {
      let body = "";
      req.on("data", (c) => (body += c));
      req.on("end", () => {
        const send = (status, obj) => {
          res.writeHead(status, { "content-type": "application/json", connection: "close" });
          res.end(JSON.stringify(obj));
        };
        if (req.headers.authorization !== `Bearer ${state.token}`) return send(401, { error: "unauthorized", message: "a bearer token is required" });
        const json = body ? JSON.parse(body) : {};
        state.requests.push({ method: req.method, path: req.url, body: json });
        const status = { screen: mode === "denied" ? "denied" : "granted", screen_detail: "", capture: "ScreenCaptureKit", accessibility: mode !== "denied", pid: state.pid, version: "0.1.38", display: { width: 1440, height: 900, scale: 2 } };
        if (req.method === "GET" && req.url === "/status") {
          send(200, status);
          if (mode === "dies") server.close();
          return;
        }
        if (req.method === "POST" && req.url === "/request") return send(200, status);
        if (req.method === "POST" && req.url === "/screenshot") {
          if (mode === "denied") return send(403, { error: "screen_denied", message: "Screen Recording is off for nanoMuse Computer Use" });
          if (mode === "fails") return send(500, { error: "screenshot_failed", message: SCK_FAILURE });
          return send(200, { base64: Buffer.from("png").toString("base64"), mime: json.format === "png" ? "image/png" : "image/jpeg", width: json.width ?? 1440, height: json.height ?? 900, screen: { width: 1440, height: 900 }, scale: 2, capture: "ScreenCaptureKit" });
        }
        if (req.method === "GET" && req.url === "/windows") {
          if (mode === "denied") return send(403, { error: "screen_denied", message: "Screen Recording is off for nanoMuse Computer Use" });
          return send(200, { windows, capture: "ScreenCaptureKit" });
        }
        if (req.method === "POST" && req.url === "/window") {
          if (mode === "denied") return send(403, { error: "screen_denied", message: "Screen Recording is off for nanoMuse Computer Use" });
          const found = windows.find((w) => w.id === json.id);
          if (!found) return send(404, { error: "no_window", message: `no window with id ${json.id} is on screen` });
          const [x, y, w, h] = found.bounds;
          return send(200, { base64: Buffer.from("window-png").toString("base64"), mime: json.format === "jpeg" ? "image/jpeg" : "image/png", width: w * 2, height: h * 2, window: { id: found.id, x, y, width: w, height: h }, scale: 2, capture: "ScreenCaptureKit" });
        }
        if (req.method === "POST" && req.url === "/execute") {
          if (!json.action) return send(400, { error: "bad_action", message: "unknown action ''" });
          return send(200, { ok: true, note: "" });
        }
        if (req.method === "POST" && req.url === "/quit") {
          state.quit += 1;
          send(200, { ok: true });
          setTimeout(() => server.close(), 50);
          return;
        }
        send(404, { error: "not_found", message: `no route ${req.method} ${req.url}` });
      });
    });
    state.servers.push(server);
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    state.port = server.address().port;
    // the real helper writes it atomically; a short delay stands for its start-up
    setTimeout(() => writeFileSync(arg("--port-file"), `${JSON.stringify({ port: state.port, pid: state.pid, version: "0.1.38" })}\n`), 30);
  };
  state.launch = launch;
  state.closeAll = () => state.servers.forEach((s) => s.close());
  return state;
}

test("absent bundle: not present, never launched, every call says so", async () => {
  const dir = scratch();
  const helper = new MacHelper({ appPath: join(dir, "nowhere.app"), dataDir: join(dir, "data") });
  assert.equal(helper.present(), false);
  assert.equal(await helper.ready(), false);
  assert.equal(helper.running(), false);
  assert.equal(helper.cachedStatus(), null);
  assert.match(helper.failure(), /no helper bundle/);
  await assert.rejects(helper.screenshot(), (exc) => exc instanceof MacHelperError && exc.status === 503 && exc.code === "not_running");
  const off = new MacHelper({ appPath: undefined, dataDir: join(dir, "data2") });
  assert.equal(off.present(), false);
  assert.equal(await off.ready(), false);
});

test("start: token file 0600 before the launch, open's arguments, port discovery, status cached", async () => {
  const dir = scratch();
  const app = fakeBundle(dir);
  const fake = fakeHelper();
  const lines = [];
  const helper = new MacHelper({ appPath: app, dataDir: join(dir, "data"), launch: fake.launch, log: (l) => lines.push(l) });
  assert.equal(helper.present(), true);
  assert.equal(await helper.ready(), true);
  assert.equal(helper.running(), true);
  assert.equal(fake.appPath, app);
  assert.deepEqual(fake.args.slice(0, 1), ["--token-file"]);
  assert.ok(fake.args.includes("--port-file"));
  assert.equal(fake.parentPid, process.pid);
  assert.equal(fake.token.length, 48);
  // the token file is the person's alone while the helper runs
  assert.equal(statSync(fake.args[1]).mode & 0o777, 0o600);
  assert.equal(statSync(join(dir, "data")).mode & 0o777, 0o700);
  // the token the fake read is the one the client sends: /status was answered 200
  const status = helper.cachedStatus();
  assert.equal(status.screen, "granted");
  assert.equal(status.accessibility, true);
  assert.equal(status.pid, 4242);
  assert.equal(status.version, "0.1.38");
  assert.deepEqual(status.display, { width: 1440, height: 900, scale: 2 });
  assert.ok(lines.some((l) => l.includes("nanoMuse Computer Use 0.1.38") && l.includes("screen granted")));
  // a second ready() is a no-op
  assert.equal(await helper.ready(), true);
  assert.equal(fake.servers.length, 1);
  await helper.stop();
  assert.equal(fake.quit, 1);
  assert.equal(helper.running(), false);
  assert.equal(existsSync(join(dir, "data", "port")), false);
  assert.equal(existsSync(join(dir, "data", "token")), false);
});

test("the endpoints map one to one: status, request, screenshot, execute", async () => {
  const dir = scratch();
  const fake = fakeHelper();
  const helper = new MacHelper({ appPath: fakeBundle(dir), dataDir: join(dir, "data"), launch: fake.launch });
  assert.equal(await helper.ready(), true);
  const asked = await helper.request("screen", true);
  assert.equal(asked.screen, "granted");
  assert.deepEqual(fake.requests.at(-1), { method: "POST", path: "/request", body: { what: "screen", pane: true } });
  const shot = await helper.screenshot({ width: 640, height: 400, format: "png", quality: 80 });
  assert.equal(shot.mime, "image/png");
  assert.equal(shot.width, 640);
  assert.equal(shot.height, 400);
  assert.deepEqual(shot.screen, { width: 1440, height: 900 });
  assert.equal(shot.scale, 2);
  assert.equal(Buffer.from(shot.base64, "base64").toString(), "png");
  assert.deepEqual(fake.requests.at(-1).body, { width: 640, height: 400, format: "png", quality: 80 });
  const done = await helper.execute({ action: "click", x: 10, y: 20 });
  assert.deepEqual(done, { ok: true, note: "" });
  assert.deepEqual(fake.requests.at(-1).body, { action: "click", x: 10, y: 20 });
  await assert.rejects(helper.execute({ action: "" }), (exc) => exc instanceof MacHelperError && exc.status === 400 && exc.code === "bad_action");
  await helper.stop();
});

test("the window routes: /windows lists, /window captures one by id, 404 when it is gone; status carries the capture source", async () => {
  const dir = scratch();
  const fake = fakeHelper();
  const helper = new MacHelper({ appPath: fakeBundle(dir), dataDir: join(dir, "data"), launch: fake.launch });
  assert.equal(await helper.ready(), true);
  assert.equal(helper.cachedStatus().capture, "ScreenCaptureKit");
  assert.equal(helper.cachedStatus().screenDetail, undefined);
  const list = await helper.windows();
  assert.equal(list.length, 2);
  assert.deepEqual(list[0], { id: 41, pid: 500, app: "Safari", bundle_id: "com.apple.Safari", title: "Apple", bounds: [100, 50, 800, 600], layer: 0, on_screen: true });
  const shot = await helper.window({ id: 41, max_pixels: 0, format: "png" });
  assert.equal(shot.mime, "image/png");
  assert.deepEqual([shot.width, shot.height], [1600, 1200]);
  assert.deepEqual(shot.window, { id: 41, x: 100, y: 50, width: 800, height: 600 });
  assert.equal(shot.scale, 2);
  assert.equal(Buffer.from(shot.base64, "base64").toString(), "window-png");
  assert.deepEqual(fake.requests.at(-1).body, { id: 41, max_pixels: 0, format: "png" });
  await assert.rejects(helper.window({ id: 99 }), (exc) => exc instanceof MacHelperError && exc.status === 404 && exc.code === "no_window" && /99/.test(exc.message));
  await helper.stop();
});

test("denied: /screenshot's 403 comes through with its code; status says denied", async () => {
  const dir = scratch();
  const fake = fakeHelper("denied");
  const helper = new MacHelper({ appPath: fakeBundle(dir), dataDir: join(dir, "data"), launch: fake.launch });
  assert.equal(await helper.ready(), true);
  assert.equal(helper.cachedStatus().screen, "denied");
  assert.equal(helper.cachedStatus().accessibility, false);
  await assert.rejects(helper.screenshot(), (exc) => exc instanceof MacHelperError && exc.status === 403 && exc.code === "screen_denied" && /nanoMuse Computer Use/.test(exc.message));
  await helper.stop();
});

test("a helper that never writes its port: ready() is false, and not retried for a while", async () => {
  const dir = scratch();
  const fake = fakeHelper("no-port");
  const lines = [];
  const helper = new MacHelper({ appPath: fakeBundle(dir), dataDir: join(dir, "data"), launch: fake.launch, startTimeoutMs: 250, retryAfterMs: 60_000, log: (l) => lines.push(l) });
  assert.equal(helper.failedToStart(), false);
  assert.equal(await helper.ready(), false);
  assert.equal(helper.failedToStart(), true);
  assert.match(helper.failure(), /no port after/);
  assert.ok(lines.some((l) => /did not start/.test(l) && /refused with this reason/.test(l)));
  assert.equal(await helper.ready(), false);
  assert.equal(fake.args !== undefined, true);
});

// ---- the operator on a Mac with the helper: its picture, or its reason — never desktopCapturer's ----

/** An operator over `fake`, on a Mac, with the helper's own permission probe (as main.ts wires it). */
function macOperator(dir, fake, extra = {}) {
  const lines = [];
  const helper = new MacHelper({ appPath: fakeBundle(dir), dataDir: join(dir, "data"), launch: fake.launch, log: (l) => lines.push(l), ...extra });
  const operator = new Operator({
    helper,
    log: (l) => lines.push(l),
    permissions: () => {
      const s = helper.cachedStatus();
      return s ? { accessibility: s.accessibility, screen: s.screen === "granted" } : { accessibility: true, screen: true };
    },
  });
  return { operator, helper, lines };
}

test("operator: the helper's picture comes through at the asked size; /info names the helper and its capture source", async (t) => {
  const dir = scratch();
  const fake = fakeHelper();
  const { operator, helper } = macOperator(dir, fake);
  t.after(() => helper.stop());
  await onDarwin(async () => {
    electronFake.captures = 0;
    const shot = await operator.screenshot({ width: 640, height: 400, format: "png" });
    assert.equal(shot.mime, "image/png");
    assert.deepEqual([shot.width, shot.height], [640, 400]);
    assert.deepEqual(shot.screen, { width: 1440, height: 900 });
    assert.equal(shot.scaleFactor, 1); // points on a Mac
    assert.equal(Buffer.from(shot.base64, "base64").toString(), "png");
    assert.deepEqual(fake.requests.at(-1).body, { width: 640, height: 400, format: "png", quality: 80 });
    assert.equal(electronFake.captures, 0);
    const info = operator.info();
    assert.equal(info.available, true);
    assert.equal(info.helper.present, true);
    assert.equal(info.helper.running, true);
    assert.equal(info.helper.capture, "ScreenCaptureKit");
    assert.equal(info.helper.pid, 4242);
  });
});

test("operator: a helper whose capture fails is reported with its own words — no desktopCapturer", async (t) => {
  const dir = scratch();
  const fake = fakeHelper("fails");
  const { operator, helper, lines } = macOperator(dir, fake);
  t.after(() => helper.stop());
  await onDarwin(async () => {
    electronFake.captures = 0;
    await assert.rejects(operator.screenshot({ width: 640, height: 400 }), (exc) => {
      assert.ok(exc instanceof OperatorError);
      assert.equal(exc.status, 500);
      assert.match(exc.message, /^no screenshot: nanoMuse Computer Use could not take the picture: /);
      assert.ok(exc.message.includes("picture: ScreenCaptureKit userDeclined (-3801)"), exc.message);
      assert.equal(exc.message.split("no screenshot:").length, 2, "the prefix is said once");
      return true;
    });
    assert.equal(electronFake.captures, 0, "desktopCapturer was used behind the helper's back");
    assert.ok(lines.some((l) => l.includes("helper screenshot failed (") && l.includes("not falling back to desktopCapturer")), lines.join("\n"));
    assert.ok(!lines.some((l) => /Electron path/.test(l)));
  });
});

test("operator: without the helper's Screen Recording grant the refusal names the helper's row", async (t) => {
  const dir = scratch();
  const fake = fakeHelper("denied");
  const { operator, helper } = macOperator(dir, fake);
  t.after(() => helper.stop());
  await onDarwin(async () => {
    electronFake.captures = 0;
    await assert.rejects(operator.screenshot(), (exc) => exc instanceof OperatorError && exc.status === 403 && exc.message === `no screenshot: ${HELPER_SCREEN_PERMISSION_TEXT}`);
    assert.equal(electronFake.captures, 0);
    assert.equal(operator.info().available, false);
    assert.match(operator.info().reason, /nanoMuse Computer Use/);
  });
});

test("operator: a helper bundle that did not start is the reason — for the picture, an action and /info; still no desktopCapturer", async (t) => {
  const dir = scratch();
  const fake = fakeHelper("no-port");
  const { operator, helper } = macOperator(dir, fake, { startTimeoutMs: 200, retryAfterMs: 60_000 });
  await onDarwin(async () => {
    electronFake.captures = 0;
    await assert.rejects(operator.screenshot(), (exc) => exc instanceof OperatorError && exc.status === 503 && /^no screenshot: nanoMuse Computer Use did not start \(no port after/.test(exc.message));
    await assert.rejects(operator.execute({ action: "click", x: 10, y: 10 }), (exc) => exc instanceof OperatorError && exc.status === 503 && /did not start/.test(exc.message));
    assert.equal(electronFake.captures, 0);
    const info = operator.info();
    assert.equal(info.available, false);
    assert.match(info.reason, /^nanoMuse Computer Use did not start \(no port after/);
    assert.equal(info.helper.running, false);
  });
  assert.equal(helper.running(), false);
});

test("operator: with no helper bundle at all the Electron path takes the picture (a build without the helper)", async () => {
  const dir = scratch();
  const lines = [];
  const helper = new MacHelper({ appPath: join(dir, "nowhere.app"), dataDir: join(dir, "data") });
  const operator = new Operator({ helper, log: (l) => lines.push(l) });
  await onDarwin(async () => {
    electronFake.captures = 0;
    const shot = await operator.screenshot({ width: 320, height: 200, format: "jpeg" });
    assert.equal(electronFake.captures, 1);
    assert.equal(Buffer.from(shot.base64, "base64").toString(), "jpeg-from-electron");
    assert.deepEqual([shot.width, shot.height], [320, 200]);
    assert.equal(operator.info().helper.reason, "no helper bundle");
    assert.equal(operator.info().helper.present, false);
    // window mode needs the helper
    await assert.rejects(operator.windows(), (exc) => exc instanceof OperatorError && exc.status === 503 && /window mode needs nanoMuse Computer Use/.test(exc.message));
  });
});

test("operator: the window routes go through the helper; its refusals and a gone window come back as the operator's errors", async (t) => {
  const dir = scratch();
  const fake = fakeHelper();
  const { operator, helper } = macOperator(dir, fake);
  t.after(() => helper.stop());
  await onDarwin(async () => {
    const list = await operator.windows();
    assert.equal(list.length, 2);
    assert.equal(list[1].app, "Notes");
    const shot = await operator.windowShot({ id: 43, max_pixels: 2_000_000, format: "png" });
    assert.deepEqual(shot.window, { id: 43, x: 0, y: 0, width: 500, height: 400 });
    assert.deepEqual(fake.requests.at(-1).body, { id: 43, max_pixels: 2000000, format: "png" });
    await assert.rejects(operator.windowShot({ id: 99 }), (exc) => exc instanceof OperatorError && exc.status === 404 && /window 99 could not be captured: no window with id 99/.test(exc.message));
    await assert.rejects(operator.windowShot({ id: 0 }), (exc) => exc instanceof OperatorError && exc.status === 400);
  });
  const refused = fakeHelper("denied");
  const second = macOperator(scratch(), refused);
  t.after(() => second.helper.stop());
  await onDarwin(async () => {
    await assert.rejects(second.operator.windows(), (exc) => exc instanceof OperatorError && exc.status === 403 && exc.message.endsWith(HELPER_SCREEN_PERMISSION_TEXT));
  });
});

test("a helper that dies: the next call fails as not_running and ready() launches it again", async (t) => {
  const dir = scratch();
  const fake = fakeHelper("dies");
  const helper = new MacHelper({ appPath: fakeBundle(dir), dataDir: join(dir, "data"), launch: fake.launch });
  assert.equal(await helper.ready(), true);
  // the fake closed its server after the first /status; the socket is refused now
  await assert.rejects(helper.status(), (exc) => exc instanceof MacHelperError && exc.code === "not_running");
  assert.equal(helper.running(), false);
  assert.equal(helper.cachedStatus(), null);
  assert.equal(await helper.ready(), true);
  assert.equal(fake.servers.length, 2);
  fake.closeAll();
});

test("restart: /quit to the old one, then a fresh launch with a new token", async (t) => {
  const dir = scratch();
  const fake = fakeHelper();
  const helper = new MacHelper({ appPath: fakeBundle(dir), dataDir: join(dir, "data"), launch: fake.launch });
  assert.equal(await helper.ready(), true);
  const first = fake.token;
  assert.equal(await helper.restart(), true);
  assert.equal(fake.quit, 1);
  assert.equal(fake.servers.length, 2);
  assert.notEqual(fake.token, first);
  assert.equal(helper.running(), true);
  await helper.stop();
});

test("restart: two at once are one — a single /quit, a single fresh launch; busy() and the last known status meanwhile", async (t) => {
  const dir = scratch();
  const fake = fakeHelper();
  const helper = new MacHelper({ appPath: fakeBundle(dir), dataDir: join(dir, "data"), launch: fake.launch });
  assert.equal(await helper.ready(), true);
  assert.equal(helper.busy(), false);
  const first = helper.restart();
  const second = helper.restart();
  assert.equal(first, second);
  // between the processes: not "not in use" — busy, and the last status stands in for the readers
  assert.equal(helper.busy(), true);
  assert.equal(helper.lastKnownStatus().screen, "granted");
  assert.deepEqual(await Promise.all([first, second]), [true, true]);
  assert.equal(fake.quit, 1);
  assert.equal(fake.servers.length, 2);
  assert.equal(helper.busy(), false);
  await helper.stop();
});

test("quarantine: a flag that came off is logged; one that stays is why the helper is not started", async () => {
  const dir = scratch();
  const fake = fakeHelper();
  const lines = [];
  const removed = new MacHelper({ appPath: fakeBundle(dir), dataDir: join(dir, "data"), launch: fake.launch, quarantine: () => ({ result: "removed", detail: "" }), log: (l) => lines.push(l) });
  assert.equal(await removed.ready(), true);
  assert.ok(lines.some((l) => /removed the quarantine flag/.test(l)));
  await removed.stop();
  const stuck = fakeHelper();
  const kept = new MacHelper({ appPath: fakeBundle(dir), dataDir: join(dir, "data2"), launch: stuck.launch, quarantine: () => ({ result: "kept", detail: "Operation not permitted" }) });
  assert.equal(await kept.ready(), false);
  assert.equal(stuck.args, undefined);
  assert.ok(kept.failure().includes(QUARANTINE_KEPT_TEXT));
  assert.match(kept.failure(), /Operation not permitted/);
});

test("clearQuarantine: xattr's answers → none, removed, kept (with what it said); nothing off macOS", () => {
  const calls = [];
  const fakeXattr = (answers) => (cmd, args) => {
    calls.push([cmd, ...args]);
    const next = answers.shift();
    return typeof next === "string" ? { status: 1, stderr: next } : next;
  };
  const absent = { status: 1, stderr: "No such xattr: com.apple.quarantine" };
  const present = { status: 0, stdout: "0083;00000000;;UUID" };
  assert.deepEqual(clearQuarantine("/x/Helper.app", fakeXattr([absent]), "darwin"), { result: "none", detail: "" });
  assert.deepEqual(calls.at(-1), ["xattr", "-p", "com.apple.quarantine", "/x/Helper.app"]);
  assert.deepEqual(clearQuarantine("/x/Helper.app", fakeXattr([present, { status: 0, stderr: "" }, absent]), "darwin"), { result: "removed", detail: "" });
  assert.deepEqual(calls.at(-2), ["xattr", "-dr", "com.apple.quarantine", "/x/Helper.app"]);
  assert.deepEqual(clearQuarantine("/x/Helper.app", fakeXattr([present, { status: 1, stderr: "xattr: [Errno 30] Read-only file system\nmore" }, present]), "darwin"), {
    result: "kept",
    detail: "xattr: [Errno 30] Read-only file system",
  });
  assert.deepEqual(clearQuarantine("/x/Helper.app", fakeXattr([present, { error: new Error("spawn xattr ENOENT") }, present]), "darwin"), { result: "kept", detail: "spawn xattr ENOENT" });
  const before = calls.length;
  assert.deepEqual(clearQuarantine("/x/Helper.app", fakeXattr([]), "linux"), { result: "none", detail: "" });
  assert.equal(calls.length, before);
});

test("an app under App Translocation does not start its helper, and says why", async () => {
  const dir = scratch();
  const app = join(dir, "AppTranslocation", "4F1C", "d", "nanoMuse.app", "Contents", "Helpers", `${HELPER_NAME}.app`);
  mkdirSync(app, { recursive: true });
  assert.equal(translocated(app), true);
  assert.equal(translocated("/Applications/nanoMuse.app/Contents/Helpers/x.app"), false);
  const fake = fakeHelper();
  const helper = new MacHelper({ appPath: app, dataDir: join(dir, "data"), launch: fake.launch, quarantine: () => ({ result: "none", detail: "" }) });
  assert.equal(helper.present(), true);
  assert.equal(await helper.ready(), false);
  assert.equal(fake.args, undefined);
  assert.match(helper.failure(), /Applications folder/);
});

test("defaultHelperPath: the env override, Contents/Helpers when packaged, the build dir in development", () => {
  assert.equal(defaultHelperPath("/x/nanoMuse.app/Contents/MacOS/nanomuse-desktop", true, "/proj", { NANOMUSE_COMPUTER_USE_APP: "/elsewhere/Helper.app" }), "/elsewhere/Helper.app");
  assert.equal(defaultHelperPath("/x/nanoMuse.app/Contents/MacOS/nanomuse-desktop", true, "/proj", {}), "/x/nanoMuse.app/Contents/Helpers/nanoMuse Computer Use.app");
  assert.equal(defaultHelperPath("/usr/bin/electron", false, "/proj", {}), "/proj/mac/computer-use/build/nanoMuse Computer Use.app");
});

test("describeAction: the glow's words, as the operator phrases them", () => {
  assert.equal(describeAction({ action: "click" }), "click");
  assert.equal(describeAction({ action: "left_double" }), "double click");
  assert.equal(describeAction({ action: "right_single" }), "right click");
  assert.equal(describeAction({ action: "drag" }), "drag");
  assert.equal(describeAction({ action: "scroll", dy: -200 }), "scroll up");
  assert.equal(describeAction({ action: "scroll" }), "scroll down");
  assert.equal(describeAction({ action: "type", text: "hello\n" }), "typing “hello”");
  assert.equal(describeAction({ action: "type", text: "x".repeat(50) }), `typing “${"x".repeat(40)}…”`);
  assert.equal(describeAction({ action: "hotkey", keys: ["cmd", "c"] }), "keys cmd + c");
  assert.equal(describeAction({ action: "wait", seconds: 99 }), "waiting 10 s");
  assert.equal(describeAction({ action: "wait" }), "waiting 1 s");
  assert.equal(describeAction({ action: "mystery" }), "mystery");
});
