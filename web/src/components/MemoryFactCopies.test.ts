import { createElement } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../api";
import { MemoryFactCopies } from "./MemoryFactCopies";

let screen: ReactTestRenderer;
const onChange = vi.fn();
function button(label: string) {
  return screen.root.findAllByType("button").find((node) => node.children.includes(label))!;
}
async function input(label: string, value: string) {
  await act(async () => { screen.root.findByProps({ "aria-label": label }).props.onChange({ target: { value } }); });
}
beforeEach(async () => {
  vi.clearAllMocks();
  vi.stubGlobal("window", { confirm: vi.fn(() => true) });
  await act(async () => { screen = create(createElement(MemoryFactCopies, { space: "work", version: 0, onChange })); });
});
afterEach(() => { act(() => screen.unmount()); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("requires inspection and confirms deletion with the reviewed revision in the selected space", async () => {
  const call = vi.spyOn(api, "memoryFactCopies").mockResolvedValueOnce({ revision: "reviewed", matches: [{ source: "remote", id: "file", before: "Synthetic CINDER-9274", after: "" }] }).mockResolvedValueOnce({ changed: 1, rules: [] });
  expect(button("Inspect copies").props.disabled).toBe(true);
  expect(button("Confirm deletion across copies")).toBeUndefined();
  await input("Old text or exact fact fragment", "CINDER-9274");
  await act(async () => { button("Inspect copies").props.onClick(); });
  expect(call).toHaveBeenLastCalledWith("work", expect.objectContaining({ action: "preview", term: "CINDER-9274" }));
  expect(screen.root.findByType("pre").children).toContain("Synthetic CINDER-9274");
  await act(async () => { button("Confirm deletion across copies").props.onClick(); });
  expect(call).toHaveBeenLastCalledWith("work", expect.objectContaining({ action: "apply", revision: "reviewed", replacement: "" }));
  expect(onChange).toHaveBeenCalledTimes(1);
});

it("invalidates preview when replacement changes or the server reports a conflict", async () => {
  const call = vi.spyOn(api, "memoryFactCopies").mockResolvedValue({ revision: "reviewed", matches: [] });
  await input("Old text or exact fact fragment", "CINDER-9274");
  await act(async () => { button("Inspect copies").props.onClick(); });
  await input("Replacement text, leave empty to delete", "WILLOW-5831");
  expect(button("Confirm replacement across copies")).toBeUndefined();
  await act(async () => { button("Inspect copies").props.onClick(); });
  call.mockRejectedValueOnce(new Error("Memory changed. Inspect copies again before applying."));
  await act(async () => { button("Confirm replacement across copies").props.onClick(); });
  expect(button("Confirm replacement across copies")).toBeUndefined();
  expect(screen.root.findByProps({ role: "alert" }).children.join("")).toContain("Memory changed");
  expect(onChange).not.toHaveBeenCalled();
});

it("does not apply when confirmation is cancelled", async () => {
  const call = vi.spyOn(api, "memoryFactCopies").mockResolvedValue({ revision: "reviewed", matches: [] });
  await input("Old text or exact fact fragment", "CINDER-9274");
  await act(async () => { button("Inspect copies").props.onClick(); });
  vi.mocked(window.confirm).mockReturnValue(false);
  await act(async () => { button("Confirm deletion across copies").props.onClick(); });
  expect(call).toHaveBeenCalledTimes(1);
  expect(onChange).not.toHaveBeenCalled();
});

it("binds alias wording to inspection and invalidates the reviewed changes on edits", async () => {
  const call = vi.spyOn(api, "memoryFactCopies").mockResolvedValue({ revision: "reviewed", matches: [] });
  await input("Old text or exact fact fragment", "CINDER-9274");
  await input("Other known wording, one per line", "Earlier wording\nAlternate Phrase");
  await act(async () => { button("Inspect copies").props.onClick(); });
  expect(call).toHaveBeenLastCalledWith("work", expect.objectContaining({ aliases: ["Earlier wording", "Alternate Phrase"] }));
  await input("Other known wording, one per line", "Another phrase");
  expect(button("Confirm deletion across copies")).toBeUndefined();
});

it("loads the durable result after partial failure and inspects before retrying", async () => {
  const call = vi.spyOn(api, "memoryFactCopies")
    .mockResolvedValueOnce({ revision: "reviewed", matches: [] })
    .mockRejectedValueOnce(new Error("Some remote changes may be incomplete"))
    .mockResolvedValueOnce({ report: { id: "operation", at: "", space: "work", fact_id: "fact", state: "incomplete", exclusions_active: true, outside_scope: [], sources: [{ source: "remote", scanned: 2, matched: 2, changed: 1, status: "incomplete" }] } })
    .mockResolvedValueOnce({ revision: "retry-review", matches: [] });
  await input("Old text or exact fact fragment", "CINDER-9274");
  await act(async () => { button("Inspect copies").props.onClick(); });
  await act(async () => { button("Confirm deletion across copies").props.onClick(); });
  expect(screen.root.findByType("table")).toBeDefined();
  expect(button("Confirm deletion across copies")).toBeUndefined();
  await act(async () => { button("Inspect remaining copies").props.onClick(); });
  expect(call).toHaveBeenLastCalledWith("work", expect.objectContaining({ action: "preview" }));
  expect(onChange).not.toHaveBeenCalled();
});
