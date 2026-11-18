import { createElement } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../api";
import { MemoryScreen } from "./MemoryScreen";

const store = vi.hoisted(() => ({
  state: {
    activeThread: "work-chat",
    threads: [{ id: "work-chat", memory_space: "work" }],
    memoryVersion: 0, profile: null,
  },
  dispatch: vi.fn(), openThread: vi.fn(), setTab: vi.fn(), toast: vi.fn(),
}));
vi.mock("../store", () => ({ useStore: () => store }));
vi.mock("../components/OpenVikingMemoryPanel", () => ({ OpenVikingMemoryPanel: () => null }));
let screen: ReactTestRenderer;

beforeEach(() => {
  vi.clearAllMocks();
  store.state.activeThread = "work-chat";
  vi.spyOn(api, "memory").mockResolvedValue([]);
  vi.spyOn(api, "memoryChanges").mockResolvedValue([]);
  vi.spyOn(api, "memorySpaces").mockResolvedValue({
    owner: "synthetic-owner", spaces: [{ id: "personal", label: "Personal" }, { id: "work", label: "Work" }],
    learning: { pending: 0, failed: 0 },
  });
});
afterEach(() => { if (screen) act(() => screen.unmount()); vi.restoreAllMocks(); });

it("opens the active conversation's space and keeps the empty-memory chat action there", async () => {
  vi.spyOn(api, "createThread").mockResolvedValue({ id: "new-work-chat", memory_space: "work" } as Awaited<ReturnType<typeof api.createThread>>);
  await act(async () => { screen = create(createElement(MemoryScreen)); });
  expect(api.memory).toHaveBeenCalledWith("work");
  expect(api.memoryChanges).toHaveBeenCalledWith(30, "work");
  const tell = screen.root.findAllByType("button").find((node) => node.children.includes("Tell nanoMuse something to remember"))!;
  await act(async () => { tell.props.onClick(); });
  expect(api.createThread).toHaveBeenCalledWith("New conversation", "work");
  expect(store.openThread).toHaveBeenCalledWith("new-work-chat");
  expect(store.openThread).not.toHaveBeenCalledWith("main");
});

it("uses the personal space for a legacy conversation without space metadata", async () => {
  store.state.activeThread = "main";
  await act(async () => { screen = create(createElement(MemoryScreen)); });
  expect(api.memory).toHaveBeenCalledWith("personal");
});
