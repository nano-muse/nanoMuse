import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "../lib/api";
import { LangContext } from "../lib/i18n";
import type { EventRow } from "../lib/types";
import { Activity } from "./Activity";

const route = vi.hoisted(() => ({ params: new URLSearchParams(), set: vi.fn() }));
vi.mock("../lib/router", () => ({ useRoute: () => route }));
vi.mock("../lib/hooks", () => ({ useData: () => ({ data: undefined }) }));
vi.mock("../lib/api", () => ({ get: vi.fn(), qs: (args: Record<string, string | number>) => `?${new URLSearchParams(Object.entries(args).map(([key, value]) => [key, String(value)]))}` }));
vi.mock("./common", () => ({ Loaded: () => null }));
vi.mock("../ui/who", () => ({ IpChip: () => null, PlatformPill: () => null, Who: () => null }));

function deferred() {
  let resolve!: (value: { events: EventRow[] }) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<{ events: EventRow[] }>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const event = (id: number, detail = `event-${id}`): EventRow => ({
  id, detail, ts: 1_800_000_000, kind: "call.ended", ip: "", ua: "",
});
let screen: ReactTestRenderer | undefined;
const page = () => <LangContext.Provider value={{ lang: "en", setLang: () => {} }}><Activity days={7} /></LangContext.Provider>;
const text = () => JSON.stringify(screen!.toJSON());

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("document", { visibilityState: "visible" });
  route.params = new URLSearchParams();
  vi.mocked(get).mockReset();
});
afterEach(() => {
  if (screen) act(() => screen!.unmount());
  screen = undefined;
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("Activity request ownership", () => {
  for (const outcome of ["success", "error"] as const) {
    it(`drops an old filter's late ${outcome}`, async () => {
      const old = deferred();
      vi.mocked(get).mockReturnValueOnce(old.promise).mockResolvedValueOnce({ events: [event(2, "current-filter")] });
      await act(async () => { screen = create(page()); });
      route.params = new URLSearchParams({ k: "budget.refused" });
      await act(async () => { screen!.update(page()); });
      await act(async () => {
        if (outcome === "success") old.resolve({ events: [event(1, "old-filter")] });
        else old.reject(new Error("old-filter-error"));
      });
      expect(text()).toContain("current-filter");
      expect(text()).not.toContain("old-filter");
    });
  }

  it("preserves a pending and loaded More page across poll ticks", async () => {
    const more = deferred();
    vi.mocked(get).mockResolvedValueOnce({ events: Array.from({ length: 200 }, (_, i) => event(400 - i)) }).mockReturnValueOnce(more.promise);
    await act(async () => { screen = create(page()); });
    const button = screen!.root.findAllByType("button").find((node) => node.props.children === "Load 200 more");
    expect(button).toBeDefined();
    act(() => { void button!.props.onClick(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(get).toHaveBeenCalledTimes(2);
    await act(async () => { more.resolve({ events: [event(199, "older-page")] }); });
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(get).toHaveBeenCalledTimes(2);
    expect(text()).toContain("older-page");
    expect(text()).toContain("event-400");
  });

  it("resumes polling after leaving a paged filter and drops its pending More answer", async () => {
    const more = deferred();
    vi.mocked(get)
      .mockResolvedValueOnce({ events: Array.from({ length: 200 }, (_, i) => event(400 - i)) })
      .mockReturnValueOnce(more.promise)
      .mockResolvedValue({ events: [event(1, "current-filter")] });
    await act(async () => { screen = create(page()); });
    const button = screen!.root.findAllByType("button").find((node) => node.props.children === "Load 200 more");
    act(() => { void button!.props.onClick(); });
    route.params = new URLSearchParams({ k: "upstream.error" });
    await act(async () => { screen!.update(page()); });
    await act(async () => { more.resolve({ events: [event(199, "previous-filter-history")] }); });
    expect(text()).toContain("current-filter");
    expect(text()).not.toContain("previous-filter-history");
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(get).toHaveBeenCalledTimes(4);
  });
});
