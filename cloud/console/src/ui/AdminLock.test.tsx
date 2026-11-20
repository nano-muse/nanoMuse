import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setLockedHandler, token } from "../lib/api";
import { en } from "../lib/locales";
import { AdminLock } from "./AdminLock";

let screen: ReactTestRenderer | undefined;
const entered = vi.fn();
const locked = vi.fn();

function storage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
    removeItem: (key: string) => { values.delete(key); },
  };
}

const input = () => screen!.root.findByType("input");
const enter = () => screen!.root.findAllByType("button").find((node) => node.props.children === "Enter")!;
const text = () => JSON.stringify(screen!.toJSON());

beforeEach(() => {
  vi.stubGlobal("sessionStorage", storage());
  vi.stubGlobal("localStorage", storage());
  vi.stubGlobal("navigator", { language: "en" });
  vi.stubGlobal("fetch", vi.fn());
  entered.mockReset();
  locked.mockReset();
  setLockedHandler(locked);
  act(() => { screen = create(<AdminLock expired={false} onEnter={entered} />); });
  act(() => { input().props.onChange({ target: { value: "  candidate  " } }); });
});

afterEach(() => {
  if (screen) act(() => screen!.unmount());
  screen = undefined;
  setLockedHandler(() => undefined);
  vi.unstubAllGlobals();
});

describe("admin console entry", () => {
  for (const failure of ["server", "offline"] as const) {
    it(`keeps input and the previous token during a ${failure} failure, then retries`, async () => {
      token.set("remembered");
      if (failure === "server") vi.mocked(fetch).mockResolvedValueOnce(new Response("{}", { status: 500 }));
      else vi.mocked(fetch).mockRejectedValueOnce(new TypeError("network unavailable"));
      await act(async () => { await enter().props.onClick(); });
      expect(text()).toContain(en.lock.unavailable);
      expect(text()).not.toContain(en.lock.bad);
      expect(input().props.value).toBe("  candidate  ");
      expect(token.get()).toBe("remembered");
      expect(entered).not.toHaveBeenCalled();
      expect(locked).not.toHaveBeenCalled();

      vi.mocked(fetch).mockResolvedValueOnce(new Response("{}", { status: 200 }));
      await act(async () => { await enter().props.onClick(); });
      expect(token.get()).toBe("candidate");
      expect(entered).toHaveBeenCalledOnce();
      expect(text()).not.toContain(en.lock.unavailable);
    });
  }

  it("calls only a real 401 a bad token and never enters", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response("{}", { status: 401 }));
    await act(async () => { await enter().props.onClick(); });
    expect(text()).toContain(en.lock.bad);
    expect(text()).not.toContain(en.lock.unavailable);
    expect(input().props.value).toBe("  candidate  ");
    expect(token.get()).toBe("");
    expect(entered).not.toHaveBeenCalled();
  });

  it("does not save an unverified candidate or submit twice through Enter", async () => {
    let finish!: (response: Response) => void;
    vi.mocked(fetch).mockReturnValue(new Promise<Response>((resolve) => { finish = resolve; }));
    act(() => {
      void input().props.onKeyDown({ key: "Enter" });
      void input().props.onKeyDown({ key: "Enter" });
    });
    expect(fetch).toHaveBeenCalledOnce();
    expect(token.get()).toBe("");
    expect(enter().props.disabled).toBe(true);
    await act(async () => { finish(new Response("{}", { status: 200 })); });
    expect(entered).toHaveBeenCalledOnce();
    expect(token.get()).toBe("candidate");
    expect(enter().props.disabled).toBe(false);
  });
  it("an unmounted validation cannot replace a newer sign-in", async () => {
    let finish!: (response: Response) => void;
    vi.mocked(fetch).mockReturnValue(new Promise<Response>((resolve) => { finish = resolve; }));
    act(() => { void enter().props.onClick(); });
    act(() => screen!.unmount());
    screen = undefined;
    token.set("newer-session");
    await act(async () => { finish(new Response("{}", { status: 200 })); });
    expect(token.get()).toBe("newer-session");
    expect(entered).not.toHaveBeenCalled();
  });

});
