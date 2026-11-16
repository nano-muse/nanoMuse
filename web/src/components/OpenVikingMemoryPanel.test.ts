import { createElement } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../api";
import { OpenVikingMemoryPanel } from "./OpenVikingMemoryPanel";

const uri = "viking://user/test-user/memories/entities/project.md";
let screen: ReactTestRenderer;

beforeEach(() => {
  vi.spyOn(api, "personalProfile").mockResolvedValue({ learning_enabled: true, items: [] });
  vi.spyOn(api, "openVikingStatus").mockResolvedValue({ enabled: true, capture: true, pending: 0, tasks: [] });
  vi.spyOn(api, "openVikingEntries").mockResolvedValue({
    root: "viking://user/test-user/memories", uri: "viking://user/test-user/memories", offset: 0, has_more: false,
    items: [{ uri, name: "project.md", directory: false, abstract: "Project identifier" }],
  });
  vi.spyOn(api, "openVikingRead").mockResolvedValue({ uri, content: "Original fact", revision: "a".repeat(64) });
});

afterEach(() => {
  if (screen) act(() => screen.unmount());
  vi.restoreAllMocks();
});

async function mountAndOpen() {
  await act(async () => { screen = create(createElement(OpenVikingMemoryPanel, { version: 0 })); });
  await act(async () => { screen.root.findByType("li").findByType("button").props.onClick(); });
}

it("keeps the unsaved edit and its revision when a concurrent update conflicts", async () => {
  vi.spyOn(api, "openVikingUpdate").mockRejectedValue(new Error("Memory changed. Reload it before saving or deleting."));
  await mountAndOpen();
  act(() => { screen.root.findByType("textarea").props.onChange({ target: { value: "My corrected fact" } }); });
  const save = screen.root.findAllByType("button").find((node) => node.children.includes("Save"))!;
  await act(async () => { save.props.onClick(); });
  expect(api.openVikingUpdate).toHaveBeenCalledWith({ uri, content: "My corrected fact", revision: "a".repeat(64) }, "personal");
  expect(screen.root.findByType("textarea").props.value).toBe("My corrected fact");
  expect(screen.root.findByProps({ role: "alert" }).children.join("")).toContain("Memory changed");
});

it("does not issue a delete when the user cancels confirmation", async () => {
  const confirm = vi.fn(() => false);
  vi.stubGlobal("window", { confirm });
  vi.spyOn(api, "openVikingDelete").mockResolvedValue({ ok: true });
  try {
    await mountAndOpen();
    const remove = screen.root.findAllByType("button").find((node) => node.children.includes("Delete"))!;
    await act(async () => { remove.props.onClick(); });
    expect(confirm).toHaveBeenCalledOnce();
    expect(api.openVikingDelete).not.toHaveBeenCalled();
    expect(screen.root.findByType("textarea").props.value).toBe("Original fact");
  } finally {
    vi.unstubAllGlobals();
  }
});

it("passes the selected space to remote recall and profile management", async () => {
  await act(async () => { screen = create(createElement(OpenVikingMemoryPanel, { version: 0, space: "work" })); });
  expect(api.openVikingStatus).toHaveBeenCalledWith("work");
  expect(api.openVikingEntries).toHaveBeenCalledWith("", "", 0, "work");
  expect(api.personalProfile).toHaveBeenCalledWith(false, "work");
});
