import { createElement } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../api";
import type { PersonalFact } from "../types";
import { PersonalProfilePanel } from "./PersonalProfilePanel";

const fact: PersonalFact = {
  id: "test-fact", key: "reply.length", kind: "preference", value: "Prefers short replies",
  scope: [], confidence: "inferred", status: "candidate", version: 1,
  updated_at: "2026-11-13T00:00:00+00:00", expires_at: null,
  evidence: [{ quote: "Could you shorten it?", at: "2026-11-13T00:00:00+00:00" }],
};
let screen: ReactTestRenderer;

beforeEach(() => {
  vi.spyOn(api, "personalProfile").mockResolvedValue({ learning_enabled: true, items: [fact] });
});
afterEach(() => {
  if (screen) act(() => screen.unmount());
  vi.restoreAllMocks();
});

async function mount() {
  await act(async () => { screen = create(createElement(PersonalProfilePanel, { version: 0 })); });
}

function button(label: string) {
  return screen.root.findAllByType("button").find((node) => node.children.includes(label))!;
}

it("shows inference and evidence and confirms only the version the user reviewed", async () => {
  vi.spyOn(api, "personalReview").mockResolvedValue({ ...fact, status: "active", confidence: "confirmed", version: 2 });
  await mount();
  expect(JSON.stringify(screen.toJSON())).toContain("Needs confirmation");
  expect(screen.root.findByType("blockquote").findByType("p").children).toContain("Could you shorten it?");
  await act(async () => { button("Use this fact").props.onClick(); });
  expect(api.personalReview).toHaveBeenCalledWith(fact, "confirm", "", "personal");
});

it("keeps the correction draft after a concurrent review conflict", async () => {
  vi.spyOn(api, "personalReview").mockRejectedValue(new Error("Personal memory changed. Reload it before editing."));
  await mount();
  act(() => { button("Correct this fact").props.onClick(); });
  act(() => { screen.root.findByType("textarea").props.onChange({ target: { value: "Prefers detailed replies" } }); });
  await act(async () => { button("Save").props.onClick(); });
  expect(screen.root.findByType("textarea").props.value).toBe("Prefers detailed replies");
  expect(screen.root.findByProps({ role: "alert" }).children.join("")).toContain("Personal memory changed");
});

it("can load expired and previous facts for review", async () => {
  await mount();
  await act(async () => { screen.root.findByType("input").props.onChange({ target: { checked: true } }); });
  expect(api.personalProfile).toHaveBeenLastCalledWith(true, "personal");
});
