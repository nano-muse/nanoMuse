import { createElement } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { setLocaleSetting } from "../i18n";
import type { MemoryChange, MemoryItem } from "../types";
import { MemoryScreen } from "./MemoryScreen";

const store = vi.hoisted(() => ({
  state: { profile: null as null, memoryVersion: 0 },
  toast: vi.fn(),
  openThread: () => {},
  setTab: () => {},
}));
vi.mock("../store", () => ({ useStore: () => store }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

// A forget logged by the runtime: the removed line in before, nothing after.
const forgetChange: MemoryChange = {
  id: "change-1",
  at: "2026-10-21T12:00:00Z",
  action: "forget",
  before: [
    {
      id: "memory-1",
      content: "Home address is 1 Test Street",
      category: "profile",
      created_at: "2026-10-20T12:00:00Z",
      source: "user",
    },
  ],
  after: null,
  reason: "",
  restored: false,
};

let screen: ReactTestRenderer;

function renderedText(): string {
  const walk = (node: unknown): string => {
    if (typeof node === "string") return node;
    if (Array.isArray(node)) return node.map(walk).join(" ");
    if (node && typeof node === "object" && "children" in node) {
      return walk((node as { children: unknown }).children);
    }
    return "";
  };
  return walk(screen.toJSON());
}

beforeEach(() => {
  store.state = { profile: null, memoryVersion: 0 };
  store.toast.mockClear();
  vi.spyOn(api, "memory").mockResolvedValue([]);
  vi.spyOn(api, "memoryChanges").mockResolvedValue([forgetChange]);
});

afterEach(() => {
  if (screen) act(() => screen.unmount());
  setLocaleSetting("en");
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("MemoryScreen recent changes", () => {
  it("labels a forget change Forgot, not Updated", async () => {
    setLocaleSetting("en");
    await act(async () => {
      screen = create(createElement(MemoryScreen));
    });
    const text = renderedText();
    expect(text).toContain("Forgot");
    expect(text).not.toContain("Updated");
    expect(text).toContain("Home address is 1 Test Street");
  });

  it("labels a forget change 已忘记 in zh-CN", async () => {
    setLocaleSetting("zh-CN");
    await act(async () => {
      screen = create(createElement(MemoryScreen));
    });
    expect(renderedText()).toContain("已忘记");
  });
});

describe("MemoryScreen reload race", () => {
  const remembered: MemoryItem = {
    id: "remembered", content: "Keep this memory", category: "profile",
    created_at: "2026-10-20T12:00:00Z", source: "user",
  };

  it("keeps the loaded list and undo history when a refresh fails", async () => {
    vi.mocked(api.memory).mockResolvedValue([remembered]);
    await act(async () => { screen = create(createElement(MemoryScreen)); });
    vi.mocked(api.memoryChanges).mockRejectedValueOnce(new Error("refresh offline"));
    store.state = { ...store.state, memoryVersion: 1 };
    await act(async () => { screen.update(createElement(MemoryScreen)); });
    expect(renderedText()).toContain(remembered.content);
    expect(renderedText()).toContain("Forgot");
    expect(store.toast).toHaveBeenCalledWith("refresh offline");
  });

  it("ignores failed loads after a newer answer or after leaving the page", async () => {
    await act(async () => { screen = create(createElement(MemoryScreen)); });
    const older = deferred<MemoryItem[]>();
    const latest = deferred<MemoryItem[]>();
    vi.mocked(api.memory).mockImplementationOnce(() => older.promise);
    store.state = { ...store.state, memoryVersion: 1 };
    await act(async () => { screen.update(createElement(MemoryScreen)); });
    store.state = { ...store.state, memoryVersion: 2 };
    await act(async () => { screen.update(createElement(MemoryScreen)); });
    await act(async () => { older.reject(new Error("old failure")); });
    expect(store.toast).not.toHaveBeenCalled();
    vi.mocked(api.memory).mockImplementationOnce(() => latest.promise);
    store.state = { ...store.state, memoryVersion: 3 };
    await act(async () => { screen.update(createElement(MemoryScreen)); });
    act(() => screen.unmount());
    await act(async () => { latest.reject(new Error("left page")); });
    expect(store.toast).not.toHaveBeenCalled();
  });

  it("does not restore a forgotten memory from a pending older list", async () => {
    vi.stubGlobal("window", { confirm: () => true });
    vi.mocked(api.memory).mockResolvedValue([remembered]);
    vi.spyOn(api, "forgetMemory").mockResolvedValue({ ok: true });
    await act(async () => { screen = create(createElement(MemoryScreen)); });
    const older = deferred<MemoryItem[]>();
    vi.mocked(api.memory).mockImplementationOnce(() => older.promise).mockResolvedValue([]);
    store.state = { ...store.state, memoryVersion: 1 };
    await act(async () => { screen.update(createElement(MemoryScreen)); });
    await act(async () => { screen.root.findByProps({ "aria-label": "Forget" }).props.onClick(); });
    expect(renderedText()).not.toContain(remembered.content);
    await act(async () => { older.resolve([remembered]); });
    expect(renderedText()).not.toContain(remembered.content);
    expect(api.memory).toHaveBeenCalledTimes(3);
  });

  it("a slower earlier load does not land over a newer one", async () => {
    setLocaleSetting("en");
    // one turn stores several memories: the server bumps the version twice in a row and
    // the first reload is still on its way when the second answers
    const older: MemoryItem[] = [
      { id: "memory-old", content: "Older snapshot sentence", category: "profile", created_at: "2026-10-20T12:00:00Z", source: "user" },
    ];
    const newer: MemoryItem[] = [
      { id: "memory-new", content: "Newer snapshot sentence", category: "profile", created_at: "2026-10-21T12:00:00Z", source: "user" },
    ];
    const first = deferred<MemoryItem[]>();
    const second = deferred<MemoryItem[]>();
    vi.mocked(api.memory)
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);
    await act(async () => {
      screen = create(createElement(MemoryScreen));
    });
    store.state = { ...store.state, memoryVersion: 1 };
    await act(async () => {
      screen.update(createElement(MemoryScreen));
    });
    await act(async () => {
      second.resolve(newer);
    });
    expect(renderedText()).toContain("Newer snapshot sentence");
    await act(async () => {
      first.resolve(older);
    });
    expect(renderedText()).toContain("Newer snapshot sentence");
    expect(renderedText()).not.toContain("Older snapshot sentence");
    expect(api.memory).toHaveBeenCalledTimes(2);
  });
});
