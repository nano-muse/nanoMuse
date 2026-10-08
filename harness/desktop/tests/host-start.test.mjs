// The wait for the Host's address (src/host-start.ts): the address ends it, the Host's exit
// fails it, and time alone never does. After the slow mark the page is told, with the last
// lines; at the cap the person is asked, and asked again a cap later when they keep waiting
// (issue #217: a Windows first start announced its address 126 s in, six seconds after the
// 120 s deadline had failed it). Run after `tsc -p tsconfig.json`.
import assert from "node:assert/strict";
import { test } from "node:test";
import { ADDRESS, CAP_MS, HostStartWatch, maskToken, SLOW_MS, TAIL_LINES, waitedText } from "../out/host-start.js";

/** Fake timers and a fake clock: `advance(ms)` runs what is due, in order. */
function clock() {
  let now = 1_000_000;
  let seq = 0;
  const timers = new Map();
  return {
    now: () => now,
    setTimer: (fn, ms) => {
      const id = ++seq;
      timers.set(id, { at: now + ms, fn });
      return id;
    },
    clearTimer: (id) => timers.delete(id),
    pending: () => timers.size,
    advance(ms) {
      const until = now + ms;
      for (;;) {
        const due = [...timers.entries()].filter(([, t]) => t.at <= until).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        now = due[1].at;
        timers.delete(due[0]);
        due[1].fn();
      }
      now = until;
    },
  };
}

function watch(c, extra = {}) {
  const slow = [];
  const cap = [];
  const w = new HostStartWatch({ now: c.now, setTimer: c.setTimer, clearTimer: c.clearTimer, onSlow: (s) => slow.push(s), onCap: (s) => cap.push(s), ...extra });
  return { w, slow, cap };
}

test("the defaults: two minutes to the slow state, ten to the question, eight lines kept", () => {
  assert.equal(SLOW_MS, 120_000);
  assert.equal(CAP_MS, 600_000);
  assert.equal(TAIL_LINES, 8);
});

test("the address settles the wait, even when it arrives split across chunks", async () => {
  const c = clock();
  const { w, slow, cap } = watch(c);
  w.stdout("profile ok\n");
  w.stdout("dsh web: http://127.0.0.1:38421/?tok");
  w.stdout("en=abcdef (LAN: http://10.0.0.2:38421/?token=abcdef)\n");
  const outcome = await w.done;
  assert.deepEqual(outcome, { kind: "ready", url: "http://127.0.0.1:38421/?token=abcdef" });
  assert.equal(w.isSlow, false);
  // nothing fires afterwards: the timers are gone
  c.advance(CAP_MS * 2);
  assert.equal(slow.length, 0);
  assert.equal(cap.length, 0);
  assert.equal(c.pending(), 0);
});

test("the address line is matched the way dsh-web-app prints it", () => {
  assert.equal(ADDRESS.exec("dsh web: http://127.0.0.1:38421/?token=xyz")?.[1], "http://127.0.0.1:38421/?token=xyz");
  assert.equal(ADDRESS.exec("dsh web: opening the default browser; pass --no-open to disable"), null);
});

test("126 s to the address is a slow start that succeeds, not a failure (issue #217)", async () => {
  const c = clock();
  const { w, slow, cap } = watch(c);
  c.advance(SLOW_MS);
  assert.equal(w.isSlow, true);
  assert.equal(slow.length, 1);
  assert.equal(slow[0].waitedMs, SLOW_MS);
  assert.equal(slow[0].silentMs, SLOW_MS, "the Host said nothing yet");
  assert.deepEqual(slow[0].tail, []);
  c.advance(6_000);
  w.stdout("dsh web: http://127.0.0.1:38421/?token=late\n");
  const outcome = await w.done;
  assert.equal(outcome.kind, "ready");
  assert.equal(w.state().waitedMs, SLOW_MS + 6_000);
  assert.equal(cap.length, 0);
});

test("while slow, every new line from the Host reaches the page, tokens masked, stderr marked", () => {
  const c = clock();
  const { w, slow } = watch(c);
  w.stdout("one\n");
  c.advance(SLOW_MS);
  assert.equal(slow.length, 1);
  c.advance(10_000);
  w.stderr("warn: something\n");
  w.stdout("two token=secret here\nthree\n");
  assert.equal(slow.length, 3);
  const last = slow[2];
  assert.deepEqual(last.tail, ["one", "! warn: something", "two token=… here", "three"]);
  assert.equal(last.waitedMs, SLOW_MS + 10_000);
  assert.equal(last.silentMs, 0);
});

test("the tail keeps the last TAIL_LINES lines only, each cut at 300 characters", () => {
  const c = clock();
  const { w } = watch(c);
  for (let i = 0; i < TAIL_LINES + 5; i++) w.stdout(`line ${i}\n`);
  w.stdout(`${"x".repeat(400)}\n`);
  const tail = w.state().tail;
  assert.equal(tail.length, TAIL_LINES);
  assert.equal(tail[0], `line ${TAIL_LINES + 5 - (TAIL_LINES - 1)}`);
  assert.equal(tail[TAIL_LINES - 1].length, 300);
  // blank chunks and whitespace lines count for nothing
  const before = w.state().tail;
  w.stdout("\n   \n");
  assert.deepEqual(w.state().tail, before);
});

test("the Host exiting before the address fails the start at once; a spawn error too", async () => {
  const c = clock();
  const a = watch(c);
  c.advance(30_000);
  a.w.exited(1, null);
  assert.deepEqual(await a.w.done, { kind: "exited", code: 1, signal: null });
  assert.equal(c.pending(), 0, "its timers are gone");
  const b = watch(c);
  const error = new Error("spawn ENOENT");
  b.w.error(error);
  assert.deepEqual(await b.w.done, { kind: "error", error });
  // a second outcome changes nothing
  b.w.stdout("dsh web: http://127.0.0.1:1/?token=x\n");
  assert.equal((await b.w.done).kind, "error");
});

test("at the cap the person is asked; keep waiting asks again a cap later; the Host is never failed on time", async () => {
  const c = clock();
  const { w, slow, cap } = watch(c);
  c.advance(CAP_MS - 1);
  assert.equal(cap.length, 0);
  c.advance(1);
  assert.equal(cap.length, 1);
  assert.equal(cap[0].waitedMs, CAP_MS);
  assert.equal(slow.length, 1, "the slow state came first, once");
  let settled = false;
  void w.done.then(() => {
    settled = true;
  });
  await Promise.resolve();
  assert.equal(settled, false);
  w.keepWaiting();
  c.advance(CAP_MS - 1);
  assert.equal(cap.length, 1);
  c.advance(1);
  assert.equal(cap.length, 2);
  assert.equal(cap[1].waitedMs, 2 * CAP_MS);
  // and it still succeeds when the address finally comes
  w.stdout("dsh web: http://127.0.0.1:38421/?token=t\n");
  assert.equal((await w.done).kind, "ready");
  assert.equal(c.pending(), 0);
});

test("dispose stops the timers without settling (the app quits while the Host starts)", async () => {
  const c = clock();
  const { w, slow, cap } = watch(c);
  w.dispose();
  c.advance(CAP_MS * 3);
  assert.equal(slow.length, 0);
  assert.equal(cap.length, 0);
  let settled = false;
  void w.done.then(() => {
    settled = true;
  });
  await Promise.resolve();
  assert.equal(settled, false);
  assert.equal(c.pending(), 0);
});

test("custom marks are honoured", () => {
  const c = clock();
  const { slow, cap } = watch(c, { slowMs: 1_000, capMs: 5_000 });
  c.advance(999);
  assert.equal(slow.length, 0);
  c.advance(1);
  assert.equal(slow.length, 1);
  c.advance(4_000);
  assert.equal(cap.length, 1);
});

test("the words for a wait, in both languages", () => {
  assert.equal(waitedText(126_000, false), "2 min");
  assert.equal(waitedText(126_000, true), "2 分钟");
  assert.equal(waitedText(600_000, false), "10 min");
  assert.equal(waitedText(45_000, false), "45 s");
  assert.equal(waitedText(45_000, true), "45 秒");
  assert.equal(maskToken("dsh web: http://127.0.0.1:1/?token=abc more"), "dsh web: http://127.0.0.1:1/?token=… more");
});
