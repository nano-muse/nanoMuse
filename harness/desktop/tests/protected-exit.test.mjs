// The protected exit (src/protected-exit.ts): the gate closes before the busy
// check, the work is named with keeping it running as the default, the
// confirmed stop is waited for, a cancel opens the gate and leaves everything
// on, and only the person's own exit ever earns the approval. Run after
// `tsc -p tsconfig.json`.
import assert from "node:assert/strict";
import { test } from "node:test";
import { ProtectedExit } from "../out/protected-exit.js";

/** A clock whose timers run when `advance` says so. */
function clock() {
  let now = 0;
  const timers = new Map();
  return {
    setTimer: (fn, ms) => {
      const id = { fn, at: now + ms };
      timers.set(id, id);
      return id;
    },
    clearTimer: (id) => timers.delete(id),
    advance(ms) {
      const until = now + ms;
      for (;;) {
        const due = [...timers.values()].filter((t) => t.at <= until).sort((a, b) => a.at - b.at)[0];
        if (!due) break;
        now = due.at;
        timers.delete(due);
        due.fn();
      }
      now = until;
    },
  };
}

/**
 * The work source the tests script: `answers` lists what each busy check
 * returns, the last one repeated; `always` pins every answer to one value.
 */
function fakeWork({ answers = [], always } = {}) {
  const calls = [];
  let queue = [...answers];
  let stops = 0;
  return {
    calls,
    get stops() {
      return stops;
    },
    busy: async () => {
      calls.push("busy");
      if (always) return always();
      return queue.length > 1 ? queue.shift() : queue[0];
    },
    setGate: async (open) => {
      calls.push(open ? "gate open" : "gate closed");
    },
    stopAll: async () => {
      calls.push("stop");
      stops += 1;
    },
  };
}

function fakeDialog(answer) {
  const asked = [];
  return {
    asked,
    confirm: async (items, intent) => {
      asked.push({ items, intent });
      return typeof answer === "function" ? answer() : answer;
    },
  };
}

function exitWork({ work, dialog, c, lines, stopTimeoutMs }) {
  return new ProtectedExit({
    work,
    dialog,
    finish: () => lines.push("finish"),
    log: (line) => lines.push(line),
    ...(c ? { setTimer: c.setTimer, clearTimer: c.clearTimer } : {}),
    ...(stopTimeoutMs !== undefined ? { stopTimeoutMs } : {}),
  });
}

const REPLY = { kind: "reply", label: "" };

test("with nothing on, the exit completes without a question: gate closed, checked, opened, finished", async () => {
  const lines = [];
  const work = fakeWork({ answers: [[]] });
  const dialog = fakeDialog(true);
  const guard = exitWork({ work, dialog, lines });
  assert.equal(await guard.requestExit("quit"), true);
  assert.deepEqual(work.calls, ["gate closed", "busy", "gate open"]);
  assert.deepEqual(lines.filter((l) => l === "finish"), ["finish"]);
  assert.deepEqual(dialog.asked, []);
  assert.equal(guard.approval, "user");
  assert.equal(guard.underWay, false);
});

test("with work on, the person is asked first and the default keeps it running", async () => {
  const lines = [];
  const work = fakeWork({ answers: [[REPLY, { kind: "task", label: "Phone" }]] });
  const dialog = fakeDialog(false);
  const guard = exitWork({ work, dialog, lines });
  assert.equal(await guard.requestExit("quit"), false);
  assert.deepEqual(work.calls, ["gate closed", "busy", "gate open"], "no stop ran and the gate opened again");
  assert.deepEqual(dialog.asked, [{ items: [REPLY, { kind: "task", label: "Phone" }], intent: "quit" }]);
  assert.equal(guard.approval, "none", "a cancelled exit is not an approved one");
  assert.deepEqual(lines.filter((l) => l === "finish"), []);
});

test("the gate closes before the busy check, so no new work starts under the hand-over", async () => {
  const lines = [];
  const work = fakeWork({ answers: [[]] });
  const guard = exitWork({ work, dialog: fakeDialog(true), lines });
  await guard.requestExit("quit");
  assert.ok(work.calls.indexOf("gate closed") < work.calls.indexOf("busy"), "the gate is closed before the check");
});

test("confirmed: the work is stopped, waited for and the exit completes", async () => {
  const lines = [];
  const work = fakeWork({ answers: [[REPLY], []] });
  const dialog = fakeDialog(true);
  const guard = exitWork({ work, dialog, lines });
  assert.equal(await guard.requestExit("quit"), true);
  assert.deepEqual(work.calls, ["gate closed", "busy", "stop", "busy"]);
  assert.deepEqual(lines.filter((l) => l === "finish"), ["finish"]);
  assert.equal(guard.approval, "user");
});

test("still busy after a stop: it stops again, and only a quiet check completes the exit", async () => {
  const lines = [];
  const work = fakeWork({ answers: [[REPLY], [REPLY], []] });
  const guard = exitWork({ work, dialog: fakeDialog(true), lines });
  assert.equal(await guard.requestExit("quit"), true);
  assert.deepEqual(work.calls, ["gate closed", "busy", "stop", "busy", "stop", "busy"]);
  assert.deepEqual(lines.filter((l) => l === "finish"), ["finish"]);
  assert.equal(guard.approval, "user");
});

test("a second request while one is under way is refused, not queued", async () => {
  const lines = [];
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  const work = {
    busy: async () => [REPLY],
    setGate: async () => undefined,
    stopAll: async () => {
      await gate;
    },
  };
  const dialog = fakeDialog(true);
  const guard = exitWork({ work, dialog, lines });
  const first = guard.requestExit("quit");
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(guard.underWay, true);
  assert.equal(await guard.requestExit("quit"), false, "the second ask does nothing");
  release();
  assert.equal(await first, true);
  assert.equal(dialog.asked.length, 1);
});

test("a stop that never answers is given up on after the deadline, and the exit completes", async () => {
  const lines = [];
  const c = clock();
  let askedToStop = false;
  const work = {
    busy: async () => (askedToStop ? [] : [REPLY]),
    setGate: async () => undefined,
    stopAll: () => {
      askedToStop = true;
      return new Promise(() => undefined);
    },
  };
  const guard = exitWork({ work, dialog: fakeDialog(true), c, lines, stopTimeoutMs: 15_000 });
  const done = guard.requestExit("quit");
  await new Promise((resolve) => setImmediate(resolve));
  c.advance(15_000);
  assert.equal(await done, true, "the deadline ends the wait, not the exit");
  assert.ok(lines.some((l) => l.includes("did not answer")));
  assert.equal(guard.approval, "user");
});

test("work still on after the stop rounds: the exit says so and completes (the Host's stop ends it)", async () => {
  const lines = [];
  const work = fakeWork({ always: () => [REPLY] });
  const guard = exitWork({ work, dialog: fakeDialog(true), lines });
  assert.equal(await guard.requestExit("quit"), true);
  assert.equal(work.stops, 3);
  assert.ok(lines.some((l) => l.includes("still on after the stop")));
  assert.equal(guard.approval, "user");
});

test("a failing question keeps the work running, as the default does", async () => {
  const lines = [];
  const work = fakeWork({ answers: [[REPLY]] });
  const dialog = fakeDialog(() => {
    throw new Error("no dialog");
  });
  const guard = exitWork({ work, dialog, lines });
  assert.equal(await guard.requestExit("quit"), false);
  assert.deepEqual(work.calls, ["gate closed", "busy", "gate open"]);
  assert.ok(lines.some((l) => l.includes("the question failed")));
});

test("a busy check that fails reads as nothing: the exit proceeds as before this existed", async () => {
  const lines = [];
  const work = {
    busy: async () => {
      throw new Error("host down");
    },
    setGate: async () => undefined,
    stopAll: async () => undefined,
  };
  const dialog = fakeDialog(true);
  const guard = exitWork({ work, dialog, lines });
  assert.equal(await guard.requestExit("quit"), true);
  assert.deepEqual(dialog.asked, []);
  assert.ok(lines.some((l) => l.includes("the busy check failed")));
  assert.equal(guard.approval, "user");
});

test("the restart-update intent reaches the question, with the same protection", async () => {
  const lines = [];
  const work = fakeWork({ answers: [[REPLY]] });
  const dialog = fakeDialog(false);
  const guard = exitWork({ work, dialog, lines });
  assert.equal(await guard.requestExit("restart-update"), false);
  assert.deepEqual(dialog.asked, [{ items: [REPLY], intent: "restart-update" }]);
});

test("restart-update keeps the gate closed through a quiet installation handoff", async () => {
  const work = fakeWork({ answers: [[]] });
  const guard = exitWork({ work, dialog: fakeDialog(true), lines: [] });
  assert.equal(await guard.requestExit("restart-update"), true);
  assert.deepEqual(work.calls, ["gate closed", "busy"]);
});

test("restart-update cancels and restores the gate when confirmed work remains", async () => {
  const work = fakeWork({ always: () => [REPLY] });
  const lines = [];
  const guard = exitWork({ work, dialog: fakeDialog(true), lines });
  assert.equal(await guard.requestExit("restart-update"), false);
  assert.equal(work.calls.at(-1), "gate open");
  assert.equal(guard.approval, "none");
  assert.equal(lines.includes("finish"), false);
});

test("restart-update refuses an unknown work state and restores the gate", async () => {
  const gates = [];
  const guard = exitWork({ work: {
    busy: async () => { throw new Error("unavailable"); },
    setGate: async (open) => { gates.push(open); },
    stopAll: async () => undefined,
  }, dialog: fakeDialog(true), lines: [] });
  assert.equal(await guard.requestExit("restart-update"), false);
  assert.deepEqual(gates, [false, true]);
});

test("restart-update cancels after a stop deadline even when a later check would be quiet", async () => {
  const gates = [];
  const c = clock();
  let stopping = false;
  const work = {
    busy: async () => stopping ? [] : [REPLY],
    setGate: async (open) => { gates.push(open); },
    stopAll: () => { stopping = true; return new Promise(() => undefined); },
  };
  const lines = [];
  const guard = exitWork({ work, dialog: fakeDialog(true), c, lines });
  const pending = guard.requestExit("restart-update");
  await new Promise((resolve) => setImmediate(resolve));
  c.advance(15_000);
  assert.equal(await pending, false);
  assert.deepEqual(gates, [false, true]);
  assert.equal(lines.includes("finish"), false);
});

test("quit with an installer cancels when a confirmed stop exceeds its deadline", async () => {
  const gates = [];
  const c = clock();
  let stopping = false;
  const guard = exitWork({ work: {
    busy: async () => stopping ? [] : [REPLY],
    setGate: async (open) => { gates.push(open); },
    stopAll: () => { stopping = true; return new Promise(() => undefined); },
  }, dialog: fakeDialog(true), c, lines: [] });
  let installed = false;
  const pending = guard.requestExit("quit", () => { installed = true; });
  await new Promise((resolve) => setImmediate(resolve));
  c.advance(15_000);
  assert.equal(await pending, false);
  assert.equal(installed, false);
  assert.deepEqual(gates, [false, true]);
  assert.equal(guard.approval, "none");
});

for (const item of [
  { kind: "reply", label: "" },
  { kind: "computer", label: "" },
  { kind: "task", label: "Phone" },
  { kind: "approval", label: "" },
]) {
  test(`Host restart protects active ${item.kind} work`, async () => {
    const work = fakeWork({ answers: [[item]] });
    const dialog = fakeDialog(false);
    const lines = [];
    let restarted = false;
    const guard = exitWork({ work, dialog, lines });
    assert.equal(await guard.requestRestart("restart-host", async () => { restarted = true; }), false);
    assert.equal(restarted, false);
    assert.deepEqual(work.calls, ["gate closed", "busy", "gate open"]);
    assert.deepEqual(dialog.asked, [{ items: [item], intent: "restart-host" }]);
  });
}

test("a confirmed Host restart stops work, restarts, then reopens admission", async () => {
  const work = fakeWork({ answers: [[REPLY], []] });
  const order = [];
  const originalGate = work.setGate;
  work.setGate = async (open) => { order.push(open ? "gate open" : "gate closed"); await originalGate(open); };
  const originalStop = work.stopAll;
  work.stopAll = async () => { order.push("stop"); await originalStop(); };
  const guard = exitWork({ work, dialog: fakeDialog(true), lines: [] });
  assert.equal(await guard.requestRestart("restart-host", async () => { order.push("restart"); }), true);
  assert.deepEqual(order, ["gate closed", "stop", "restart", "gate open"]);
  assert.equal(guard.approval, "none");
});

test("a failed Host restart restores admission", async () => {
  const work = fakeWork({ answers: [[]] });
  const guard = exitWork({ work, dialog: fakeDialog(true), lines: [] });
  assert.equal(await guard.requestRestart("restart-host", async () => { throw new Error("boot failed"); }), false);
  assert.deepEqual(work.calls, ["gate closed", "busy", "gate open"]);
});

test("a confirmed Host restart is cancelled and reopens admission when stopping fails", async () => {
  const work = fakeWork({ answers: [[REPLY]] });
  work.stopAll = async () => {
    work.calls.push("stop");
    throw new Error("stop failed");
  };
  let restarted = false;
  const guard = exitWork({ work, dialog: fakeDialog(true), lines: [] });
  assert.equal(await guard.requestRestart("restart-host", async () => { restarted = true; }), false);
  assert.equal(restarted, false);
  assert.deepEqual(work.calls, ["gate closed", "busy", "stop", "gate open"]);
});

test("a confirmed Host restart is cancelled and reopens admission when work remains", async () => {
  const work = fakeWork({ always: () => [REPLY] });
  let restarted = false;
  const guard = exitWork({ work, dialog: fakeDialog(true), lines: [] });
  assert.equal(await guard.requestRestart("restart-host", async () => { restarted = true; }), false);
  assert.equal(restarted, false);
  assert.equal(work.stops, 3);
  assert.equal(work.calls.at(-1), "gate open");
});

test("a confirmed Host restart is cancelled and reopens admission after a stop deadline", async () => {
  const c = clock();
  const gates = [];
  const work = {
    busy: async () => [REPLY],
    setGate: async (open) => { gates.push(open); },
    stopAll: () => new Promise(() => undefined),
  };
  let restarted = false;
  const guard = exitWork({ work, dialog: fakeDialog(true), c, lines: [], stopTimeoutMs: 15_000 });
  const pending = guard.requestRestart("restart-host", async () => { restarted = true; });
  await new Promise((resolve) => setImmediate(resolve));
  c.advance(15_000);
  assert.equal(await pending, false);
  assert.equal(restarted, false);
  assert.deepEqual(gates, [false, true]);
});

test("a Host that answers nothing is restarted all the same: that is what the restart is for", async () => {
  const work = {
    busy: async () => { throw new Error("ECONNREFUSED"); },
    setGate: async () => { throw new Error("ECONNREFUSED"); },
    stopAll: async () => { throw new Error("ECONNREFUSED"); },
  };
  const dialog = fakeDialog(true);
  let restarted = false;
  const guard = exitWork({ work, dialog, lines: [] });
  assert.equal(await guard.requestRestart("restart-host", async () => { restarted = true; }), true);
  assert.equal(restarted, true);
  assert.deepEqual(dialog.asked, []);
  assert.equal(guard.approval, "none");
});

test("a whole-app relaunch keeps the gate closed and counts as the person's exit", async () => {
  const work = fakeWork({ answers: [[]] });
  const guard = exitWork({ work, dialog: fakeDialog(true), lines: [] });
  assert.equal(await guard.requestRestart("relaunch", () => undefined, true), true);
  assert.deepEqual(work.calls, ["gate closed", "busy"]);
  assert.equal(guard.approval, "user");
});
