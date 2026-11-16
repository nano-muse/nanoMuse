import { createElement } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../api";
import { MemorySpacesPanel } from "./MemorySpacesPanel";

const { openThread, setTab } = vi.hoisted(() => ({ openThread: vi.fn(), setTab: vi.fn() }));
vi.mock("../store", () => ({ useStore: () => ({ openThread, setTab }) }));
let screen: ReactTestRenderer;
const onSpace = vi.fn();
const onChange = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(api, "memorySpaces").mockResolvedValue({ owner: "synthetic-owner", spaces: [{ id: "personal", label: "Personal" }, { id: "work", label: "Work" }], learning: { pending: 2, failed: 1 } });
});
afterEach(() => { if (screen) act(() => screen.unmount()); vi.restoreAllMocks(); });
async function mount() {
  await act(async () => { screen = create(createElement(MemorySpacesPanel, { space: "work", onSpace, onChange, version: 0 })); });
}
function button(label: string) {
  return screen.root.findAllByType("button").find((node) => node.children.includes(label))!;
}

it("starts a new conversation bound to the selected memory space", async () => {
  vi.spyOn(api, "createThread").mockResolvedValue({ id: "work-chat" } as Awaited<ReturnType<typeof api.createThread>>);
  await mount();
  await act(async () => { button("Start a conversation in this space").props.onClick(); });
  expect(api.createThread).toHaveBeenCalledWith("New conversation", "work");
  expect(openThread).toHaveBeenCalledWith("work-chat");
  expect(setTab).toHaveBeenCalledWith("chat");
});

it("retries failed profile learning only for the selected space", async () => {
  vi.spyOn(api, "retryLearning").mockResolvedValue({ ok: true });
  await mount();
  expect(api.memorySpaces).toHaveBeenCalledWith("work");
  await act(async () => { button("Retry profile learning").props.onClick(); });
  expect(api.retryLearning).toHaveBeenCalledWith("work");
  expect(onChange).toHaveBeenCalled();
});

it("requires an export before offering to clear a memory space", async () => {
  vi.spyOn(api, "clearMemorySpace").mockResolvedValue({ ok: true });
  await mount();
  expect(button("Clear after exporting").props.disabled).toBe(true);
  expect(api.clearMemorySpace).not.toHaveBeenCalled();
});

it("keeps the new space name when the server refuses creation", async () => {
  vi.spyOn(api, "createMemorySpace").mockRejectedValue(new Error("Denied by policy"));
  await mount();
  const input = screen.root.findByProps({ "aria-label": "New space name" });
  act(() => input.props.onChange({ target: { value: "Project A" } }));
  await act(async () => { button("Add space").props.onClick(); });
  expect(input.props.value).toBe("Project A");
  expect(onSpace).not.toHaveBeenCalled();
  expect(screen.root.findByProps({ role: "alert" }).children).toContain("Denied by policy");
});

it("rejects oversized backup files before sending their contents", async () => {
  vi.spyOn(api, "restoreMemorySpace").mockResolvedValue({ ok: true });
  await mount();
  const input = screen.root.findByProps({ type: "file" });
  await act(async () => { input.props.onChange({ target: { files: [{ size: 10_000_001 }], value: "" } }); });
  expect(api.restoreMemorySpace).not.toHaveBeenCalled();
  expect(screen.root.findByProps({ role: "alert" }).children).toContain("Memory backup exceeds 10 MB");
});
