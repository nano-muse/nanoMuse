import { describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({ api: { providers: vi.fn() } }));

import { api } from "./api";
import { invalidateProviders, loadProviders } from "./providers";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => {
    resolve = yes;
  });
  return { promise, resolve };
}

const view = (name: string) =>
  ({ providers: [{ id: name }], region: "", configured: {}, unavailable: {} }) as never;

// a sign-out calls invalidateProviders while an unanswered /api/providers is
// still in flight; that answer must not write the signed-out view back into
// the cache after the invalidation

describe("loadProviders", () => {
  it("an answer that started before an invalidation does not repopulate it", async () => {
    const stale = deferred<never>();
    vi.mocked(api.providers).mockReturnValueOnce(stale.promise as never);
    const first = loadProviders();
    invalidateProviders();
    stale.resolve(view("before-signout"));
    await first;

    const fresh = deferred<never>();
    vi.mocked(api.providers).mockReturnValueOnce(fresh.promise as never);
    const second = loadProviders(); // must fetch again, not serve the stale cache
    expect(api.providers, "the invalidated view was served without a refetch").toHaveBeenCalledTimes(2);
    fresh.resolve(view("after-signin"));
    await second;

    const third = loadProviders(); // now the fresh answer is cached
    await third;
    expect(api.providers).toHaveBeenCalledTimes(2);
  });
});
