import type { ReactNode } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DemoVisit } from "../lib/types";
import { Bars } from "../ui/charts";
import { Demo } from "./Demo";

const replies = vi.hoisted(() => new Map<string, unknown>());
vi.mock("../lib/hooks", () => ({ useData: (url: string) => ({ data: replies.get(url) }), useNow: () => Date.now() / 1000 }));
vi.mock("../lib/router", () => ({ useRoute: () => ({ params: new URLSearchParams(), set: () => {} }) }));
vi.mock("../ui/charts", () => ({ Bars: vi.fn(() => null), Ranks: () => null }));
vi.mock("../ui/who", () => ({ Ago: () => null, Who: () => null, IpChip: () => null, identOf: (id: string) => id }));
vi.mock("./common", () => ({ Loaded: ({ q, children }: { q: { data: unknown }; children: (data: unknown) => ReactNode }) => q.data === undefined ? null : children(q.data) }));

let screen: ReactTestRenderer | undefined;
const visit = (id: string, started: number, ended: number | null): DemoVisit => ({
  id, started, ended, reason: "", visitor: "", byok: false, ua: "", ip: "",
});
beforeEach(() => { replies.clear(); vi.clearAllMocks(); vi.useFakeTimers(); });
afterEach(() => { if (screen) act(() => screen!.unmount()); screen = undefined; vi.useRealTimers(); });

describe("Demo chart at the site's midnight", () => {
  it.each([8, 0, -7])("keeps buckets and labels together at offset %s, counting active visits once", async (offsetH) => {
    const midnight = Date.UTC(2026, 10, 1) / 1000 - offsetH * 3600;
    vi.setSystemTime((midnight + 3600) * 1000);
    const active = visit("running", midnight + 1, null);
    replies.set("/v1/admin/demo?days=2", {
      available: true, active: [active], visits: [visit("ended", midnight - 1, midnight), active],
    });
    replies.set("/v1/admin/overview?days=7", { settings: { day_offset_h: offsetH } });
    await act(async () => { screen = create(<Demo days={2} />); });
    const chart = vi.mocked(Bars).mock.calls[0][0];
    expect(chart.series[0].values).toEqual([1, 1]);
    expect(chart.labels).toEqual(["10-31", "11-01"]);
  });
});
