import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, download, get, setLockedHandler, token } from "./api";

const locked = vi.fn();

function storage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
    removeItem: (key: string) => { values.delete(key); },
  };
}

beforeEach(() => {
  vi.stubGlobal("sessionStorage", storage());
  vi.stubGlobal("fetch", vi.fn());
  locked.mockReset();
  setLockedHandler(locked);
});

afterEach(() => {
  setLockedHandler(() => undefined);
  vi.unstubAllGlobals();
});

describe("admin request authentication ownership", () => {
  it("keeps saved credentials when candidate validation fails on the server", async () => {
    token.set("remembered");
    vi.mocked(fetch).mockResolvedValue(new Response("{}", { status: 500 }));
    await expect(get("/v1/admin/health", "candidate")).rejects.toMatchObject({ status: 500 });
    expect(vi.mocked(fetch).mock.calls[0][1]?.headers).toMatchObject({ "X-Admin-Token": "candidate" });
    expect(token.get()).toBe("remembered");
    expect(locked).not.toHaveBeenCalled();
  });

  it("keeps saved credentials when the network is unavailable", async () => {
    token.set("remembered");
    vi.mocked(fetch).mockRejectedValue(new TypeError("network unavailable"));
    await expect(api("GET", "/v1/admin/health")).rejects.toMatchObject({ status: 0, code: "offline" });
    expect(token.get()).toBe("remembered");
    expect(locked).not.toHaveBeenCalled();
  });

  for (const [name, request] of [
    ["JSON", () => api("GET", "/v1/admin/health")],
    ["download", () => download("/v1/admin/stats/test.csv", "test.csv")],
  ] as const) {
    it(`${name} requests clear the same saved token when it is rejected`, async () => {
      token.set("rejected");
      vi.mocked(fetch).mockResolvedValue(new Response("{}", { status: 401 }));
      await expect(request()).rejects.toMatchObject({ status: 401 });
      expect(token.get()).toBe("");
      expect(locked).toHaveBeenCalledOnce();
    });

    it(`${name} requests cannot undo a newer acceptance of the same token`, async () => {
      let finish!: (response: Response) => void;
      vi.mocked(fetch).mockReturnValue(new Promise<Response>((resolve) => { finish = resolve; }));
      token.set("same-value");
      const pending = request();
      token.set("same-value");
      finish(new Response("{}", { status: 401 }));
      await expect(pending).rejects.toMatchObject({ status: 401 });
      expect(token.get()).toBe("same-value");
      expect(locked).not.toHaveBeenCalled();
    });

    it(`${name} requests cannot lock a newer sign-in when an old rejection arrives`, async () => {
      let finish!: (response: Response) => void;
      vi.mocked(fetch).mockReturnValue(new Promise<Response>((resolve) => { finish = resolve; }));
      token.set("previous");
      const pending = request();
      token.set("current");
      finish(new Response("{}", { status: 401 }));
      await expect(pending).rejects.toMatchObject({ status: 401 });
      expect(token.get()).toBe("current");
      expect(locked).not.toHaveBeenCalled();
    });
  }
});
