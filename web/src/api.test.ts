import { afterEach, describe, expect, it, vi } from "vitest";
import { closeOutcome, connectWs, failureDetail, WS_GONE, WS_UNAUTHORIZED } from "./api";

/** A WebSocket stand-in the test closes by hand. */
class FakeSocket {
  static made: FakeSocket[] = [];
  static OPEN = 1;
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: ((ev: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {
    FakeSocket.made.push(this);
  }
  send() {}
  close() {
    this.onclose?.({ code: 1000 });
  }
}

/** The test runs in node: `window` with a location, the timers and no stored token. */
function stubWindow(location: { protocol: string; host: string }) {
  const full = { ...location, href: `${location.protocol}//${location.host}/` };
  vi.stubGlobal("window", { location: full, setTimeout, clearTimeout, history: { replaceState: () => undefined } });
  vi.stubGlobal("location", full);
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
}

describe("failureDetail", () => {
  it("keeps the runtime's sentence", () => {
    expect(failureDetail(409, { detail: "thread is busy" })).toBe("thread is busy");
  });

  it("never shows a validation list, a JSON body or the status number", () => {
    const list = failureDetail(422, { detail: [{ loc: ["body", "text"], msg: "field required", type: "missing" }] });
    expect(list).toBe("Your nanoMuse could not do that.");
    expect(failureDetail(500, undefined)).toBe("Your nanoMuse hit a problem; try again in a moment.");
    expect(failureDetail(502, { error: "upstream" })).toBe("Your nanoMuse hit a problem; try again in a moment.");
    expect(failureDetail(404, { detail: "" })).toBe("Your nanoMuse could not do that.");
    for (const text of [list, failureDetail(500, undefined)]) {
      expect(text).not.toMatch(/\d{3}|\[object|\{/);
    }
  });
});

describe("closeOutcome", () => {
  it("sorts close codes into retry, auth and gone", () => {
    expect(closeOutcome(1006)).toBe("retry");
    expect(closeOutcome(1000)).toBe("retry");
    expect(closeOutcome(WS_UNAUTHORIZED)).toBe("auth");
    expect(closeOutcome(WS_GONE)).toBe("gone");
  });
});

describe("connectWs", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    FakeSocket.made = [];
  });

  it("reconnects after an ordinary drop, and stops for good when the gateway says the session is gone", () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeSocket);
    stubWindow({ protocol: "https:", host: "s1.s.nanomuse.dev" });
    const gone = vi.fn();
    const closed = vi.fn();
    connectWs({ onMessage: () => undefined, onClose: closed, onGone: gone });
    expect(FakeSocket.made).toHaveLength(1);
    expect(FakeSocket.made[0].url.startsWith("wss://s1.s.nanomuse.dev/ws")).toBe(true);

    // a drop mid-way: one retry after the first backoff step
    FakeSocket.made[0].onclose?.({ code: 1006 });
    expect(closed).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(600);
    expect(FakeSocket.made).toHaveLength(2);

    // the session has ended: the gateway closes with 4404 — no more sockets, ever
    FakeSocket.made[1].onclose?.({ code: WS_GONE });
    expect(gone).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.made).toHaveLength(2);
  });

  it("asks for the token on 4401 instead of retrying", () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeSocket);
    stubWindow({ protocol: "http:", host: "127.0.0.1:8793" });
    const auth = vi.fn();
    connectWs({ onMessage: () => undefined, onAuthError: auth });
    FakeSocket.made[0].onclose?.({ code: WS_UNAUTHORIZED });
    expect(auth).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.made).toHaveLength(1);
  });
});
