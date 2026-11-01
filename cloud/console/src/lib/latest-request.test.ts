import { describe, expect, it } from "vitest";
import { LatestRequest } from "./latest-request";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

describe("paged requests", () => {
  for (const outcome of ["success", "error"] as const) {
    it(`ignores an old More page's ${outcome} and busy reset after a filter changes`, async () => {
      const requests = new LatestRequest();
      const old = deferred<string[]>();
      const current = deferred<string[]>();
      const state = { rows: ["old first page"], loading: false, error: "" };
      const handlers = (append: boolean) => ({
        start: () => { state.loading = true; state.error = ""; },
        success: (rows: string[]) => { state.rows = append ? [...state.rows, ...rows] : rows; },
        error: (error: unknown) => { state.error = String(error); },
        finish: () => { state.loading = false; },
      });
      const first = requests.run(() => old.promise, handlers(true));
      state.rows = [];
      const second = requests.run(() => current.promise, handlers(false));
      if (outcome === "success") old.resolve(["old second page"]);
      else old.reject(new Error("old filter failed"));
      await first;
      expect(state).toEqual({ rows: [], loading: true, error: "" });
      current.resolve(["matching row"]);
      await second;
      expect(state).toEqual({ rows: ["matching row"], loading: false, error: "" });
    });
  }

  it("keeps the new page when the old one finishes last", async () => {
    const requests = new LatestRequest();
    const old = deferred<string>();
    const calls: string[] = [];
    const handlers = {
      start: () => {}, success: (value: string) => { calls.push(value); },
      error: () => { calls.push("error"); }, finish: () => { calls.push("finish"); },
    };
    const first = requests.run(() => old.promise, handlers);
    await requests.run(() => Promise.resolve("current"), handlers);
    old.resolve("old");
    await first;
    expect(calls).toEqual(["current", "finish"]);
  });

  it("reports a current failure and permits retry", async () => {
    const requests = new LatestRequest();
    const calls: string[] = [];
    const handlers = {
      start: () => {}, success: (value: string) => { calls.push(value); },
      error: () => { calls.push("error"); }, finish: () => { calls.push("finish"); },
    };
    await requests.run<string>(() => Promise.reject(new Error("offline")), handlers);
    await requests.run(() => Promise.resolve("retried"), handlers);
    expect(calls).toEqual(["error", "finish", "retried", "finish"]);
  });

  it("drops a response after the view unmounts", async () => {
    const requests = new LatestRequest();
    const pending = deferred<string>();
    const calls: string[] = [];
    const task = requests.run(() => pending.promise, {
      start: () => {}, success: () => { calls.push("success"); },
      error: () => { calls.push("error"); }, finish: () => { calls.push("finish"); },
    });
    requests.invalidate();
    pending.resolve("late");
    await task;
    expect(calls).toEqual([]);
  });
});
