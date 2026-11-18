import { createElement } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../api";
import type { ThreadMeta } from "../types";
import { ThreadList } from "./ChatScreen";

const store = vi.hoisted(() => ({ state: { hub: null }, dispatch: vi.fn(), toast: vi.fn() }));
vi.mock("../store", () => ({ useStore: () => store }));
let screen: ReactTestRenderer;
afterEach(() => { if (screen) act(() => screen.unmount()); vi.restoreAllMocks(); });

it("creates follow-up chats in the active work space and displays their space", async () => {
  const threads = [{ id: "work-chat", title: "Work chat", memory_space: "work", events: 0 }] as ThreadMeta[];
  const onPick = vi.fn();
  vi.spyOn(api, "createThread").mockResolvedValue({ id: "new-work-chat", memory_space: "work" } as ThreadMeta);
  await act(async () => { screen = create(createElement(ThreadList, { threads, active: "work-chat", onPick })); });
  expect(JSON.stringify(screen.toJSON())).toContain("Work");
  await act(async () => { screen.root.findByProps({ "aria-label": "New" }).props.onClick(); });
  expect(api.createThread).toHaveBeenCalledWith("Side chat", "work");
  expect(onPick).toHaveBeenCalledWith("new-work-chat");
});
