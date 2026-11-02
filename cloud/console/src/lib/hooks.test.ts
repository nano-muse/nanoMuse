import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  ApiError: class ApiError extends Error {
    status = 0;
    code = "";
    constructor(status: number, code: string, message: string) {
      super(message);
      this.status = status;
      this.code = code;
    }
  },
  get: vi.fn(),
}));

import { get, ApiError } from "./api";
import { cachedAnswer, clearCache, fetchInto } from "./hooks";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.mocked(get).mockReset();
  clearCache();
});

describe("the session cache", () => {
  it("a late answer does not overwrite the fresher one", async () => {
    const stale = deferred<{ name: string }>();
    const fresh = deferred<{ name: string }>();
    vi.mocked(get).mockReturnValueOnce(stale.promise).mockReturnValueOnce(fresh.promise);
    const first = fetchInto("/v1/people").catch(() => undefined);
    const second = fetchInto("/v1/people", true).catch(() => undefined);
    fresh.resolve({ name: "new" });
    await second;
    expect(cachedAnswer("/v1/people")?.data).toEqual({ name: "new" });
    stale.resolve({ name: "old" });
    await first;
    expect(cachedAnswer("/v1/people")?.data).toEqual({ name: "new" });
  });

  it("a late failure does not flag a fresher success", async () => {
    const stale = deferred<unknown>();
    const fresh = deferred<unknown>();
    vi.mocked(get).mockReturnValueOnce(stale.promise).mockReturnValueOnce(fresh.promise);
    const first = fetchInto("/v1/people").catch(() => undefined);
    const second = fetchInto("/v1/people", true).catch(() => undefined);
    fresh.resolve({ name: "new" });
    await second;
    stale.reject(new ApiError(504, "late", "the poll's request failed late"));
    await first;
    const answer = cachedAnswer("/v1/people");
    expect(answer?.data).toEqual({ name: "new" });
    expect(answer?.error).toBeNull();
  });

  it("the newest answer still lands", async () => {
    vi.mocked(get).mockReturnValueOnce(Promise.resolve({ name: "only" }));
    await fetchInto("/v1/people");
    const answer = cachedAnswer("/v1/people");
    expect(answer?.data).toEqual({ name: "only" });
    expect(answer?.error).toBeNull();
    expect(answer && answer.at > 0).toBe(true);
  });

  it("a cleared cache stays empty when an old request finishes", async () => {
    const stale = deferred<unknown>();
    vi.mocked(get).mockReturnValueOnce(stale.promise);
    const first = fetchInto("/v1/people");
    clearCache();
    stale.resolve({ name: "previous account" });
    await first;
    expect(cachedAnswer("/v1/people")).toBeUndefined();
  });

  it.each([false, true])("a cleared cache never reuses an old generation (failure: %s)", async (fails) => {
    const stale = deferred<unknown>();
    const fresh = deferred<unknown>();
    vi.mocked(get).mockReturnValueOnce(stale.promise).mockReturnValueOnce(fresh.promise);
    const first = fetchInto("/v1/people").catch(() => undefined);
    clearCache();
    const second = fetchInto("/v1/people");
    fresh.resolve({ name: "current account" });
    await second;
    if (fails) stale.reject(new ApiError(401, "old", "previous account"));
    else stale.resolve({ name: "previous account" });
    await first;
    expect(cachedAnswer("/v1/people")?.data).toEqual({ name: "current account" });
    expect(cachedAnswer("/v1/people")?.error).toBeNull();
  });

  it("deduplicates a normal request that is already running", async () => {
    const pending = deferred<unknown>();
    vi.mocked(get).mockReturnValueOnce(pending.promise);
    const first = fetchInto("/v1/people");
    expect(fetchInto("/v1/people")).toBe(first);
    expect(get).toHaveBeenCalledTimes(1);
    pending.resolve({ name: "only" });
    await first;
  });
});
