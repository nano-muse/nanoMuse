import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({ api: { providers: vi.fn() } }));

import { api } from "./api";
import { invalidateProviders, loadProviders } from "./providers";
import type { ProvidersView } from "./types";

function deferred() {
  let resolve!: (value: ProvidersView) => void;
  const promise = new Promise<ProvidersView>((yes) => { resolve = yes; });
  return { promise, resolve };
}

const view = (region: ProvidersView["region"]): ProvidersView => ({
  providers: [], region, configured: {}, capabilities: [], unavailable: {},
});

beforeEach(() => {
  invalidateProviders();
  vi.mocked(api.providers).mockReset();
});

describe("provider cache invalidation", () => {
  it("does not reuse an older request after sign-out or let it replace a fresh cache", async () => {
    const stale = deferred();
    const fresh = deferred();
    vi.mocked(api.providers).mockReturnValueOnce(stale.promise).mockReturnValueOnce(fresh.promise);
    const first = loadProviders();
    invalidateProviders();
    const second = loadProviders();
    expect(api.providers).toHaveBeenCalledTimes(2);
    fresh.resolve(view("global"));
    await second;
    stale.resolve(view("cn"));
    await first;
    expect((await loadProviders()).region).toBe("global");
    expect(api.providers).toHaveBeenCalledTimes(2);
  });

  it("does not let an old completion detach a newer request", async () => {
    const stale = deferred();
    const fresh = deferred();
    vi.mocked(api.providers).mockReturnValueOnce(stale.promise).mockReturnValueOnce(fresh.promise);
    const first = loadProviders();
    invalidateProviders();
    const second = loadProviders();
    stale.resolve(view("cn"));
    await first;
    const joined = loadProviders();
    expect(api.providers).toHaveBeenCalledTimes(2);
    fresh.resolve(view("global"));
    expect((await second).region).toBe("global");
    expect((await joined).region).toBe("global");
  });

  it("refetches after an invalidated request finishes with no replacement", async () => {
    const stale = deferred();
    vi.mocked(api.providers).mockReturnValueOnce(stale.promise).mockResolvedValueOnce(view("global"));
    const first = loadProviders();
    invalidateProviders();
    stale.resolve(view("cn"));
    await first;
    expect((await loadProviders()).region).toBe("global");
    expect(api.providers).toHaveBeenCalledTimes(2);
  });
});
