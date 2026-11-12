import { act } from "react";
import { create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setLocaleSetting } from "../i18n";
import type { SentinelReviewUpdate, SentinelReviewView } from "../types";
import { SentinelReviewSettings } from "./SentinelReviewSettings";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const off: SentinelReviewView = { mode: "off", provider: "", model: "", base_url: "", has_api_key: false };
const custom: SentinelReviewView = { mode: "observe", provider: "openai", model: "review-model", base_url: "https://example.org/v1", has_api_key: true };
const mounted: ReactTestRenderer[] = [];

function mount(value: SentinelReviewView, onSave: (update: SentinelReviewUpdate) => Promise<SentinelReviewView> = vi.fn(async () => value)) {
  let r!: ReactTestRenderer;
  act(() => { r = create(<SentinelReviewSettings value={value} chatModel="chat-model" onSave={onSave} />); });
  mounted.push(r);
  return { r, onSave };
}

async function submit(r: ReactTestRenderer) {
  await act(async () => r.root.findByType("form").props.onSubmit({ preventDefault: () => undefined }));
}

beforeEach(() => setLocaleSetting("en"));
afterEach(() => { act(() => mounted.splice(0).forEach((r) => r.unmount())); });

describe("observe-only review settings", () => {
  it("starts off and enables observation using the chat model without changing permissions", async () => {
    const { r, onSave } = mount(off);
    const toggle = r.root.findByProps({ type: "checkbox" });
    expect(toggle.props.checked).toBe(false);
    expect(r.root.findAllByProps({ type: "password" })).toHaveLength(0);
    expect(r.root.findByProps({ type: "submit" }).props.disabled).toBe(true);
    act(() => toggle.props.onChange({ target: { checked: true } }));
    expect(r.root.findByType("select").props.value).toBe("chat");
    await submit(r);
    expect(onSave).toHaveBeenCalledExactlyOnceWith({ mode: "observe", provider: "", model: "", base_url: "", api_key: "" });
  });

  it("preserves a saved credential when a blank key accompanies a model edit", async () => {
    const { r, onSave } = mount(custom);
    expect(r.root.findByProps({ type: "password" }).props.value).toBe("");
    act(() => r.root.findByProps({ placeholder: "Leave blank to use the chat model name" }).props.onChange({ target: { value: " other-model " } }));
    await submit(r);
    expect(onSave).toHaveBeenCalledExactlyOnceWith({ mode: "observe", provider: "openai", model: "other-model", base_url: "https://example.org/v1" });
  });

  it("clears all separate settings, including the key, when switching back to chat", async () => {
    const { r, onSave } = mount(custom);
    act(() => r.root.findAllByType("select")[0].props.onChange({ target: { value: "chat" } }));
    expect(r.root.findAllByProps({ type: "password" })).toHaveLength(0);
    await submit(r);
    expect(onSave).toHaveBeenCalledExactlyOnceWith({ mode: "observe", provider: "", model: "", base_url: "", api_key: "" });
  });

  it("only sends an empty key after explicitly choosing to clear it", async () => {
    const { r, onSave } = mount(custom);
    const clearKey = r.root.findAllByProps({ type: "checkbox" })[1];
    act(() => clearKey.props.onChange({ target: { checked: true } }));
    await submit(r);
    expect(onSave).toHaveBeenCalledExactlyOnceWith({ mode: "observe", provider: "openai", model: "review-model", base_url: "https://example.org/v1", api_key: "" });
  });

  it("leaves the custom endpoint and credentials intact when turning observation off", async () => {
    const { r, onSave } = mount(custom);
    act(() => r.root.findAllByProps({ type: "checkbox" })[0].props.onChange({ target: { checked: false } }));
    await submit(r);
    expect(onSave).toHaveBeenCalledExactlyOnceWith({ mode: "off", provider: "openai", model: "review-model", base_url: "https://example.org/v1" });
  });

  it("does not carry a typed credential to a different endpoint", async () => {
    const { r, onSave } = mount(custom);
    act(() => r.root.findByProps({ type: "password" }).props.onChange({ target: { value: "replacement-credential" } }));
    act(() => r.root.findByProps({ type: "url" }).props.onChange({ target: { value: "https://example.com/v1" } }));
    expect(r.root.findByProps({ type: "password" }).props.value).toBe("");
    expect(r.root.findByProps({ type: "password" }).props.placeholder).toBe("API key (optional)");
    await submit(r);
    expect(onSave).toHaveBeenCalledExactlyOnceWith({ mode: "observe", provider: "openai", model: "review-model", base_url: "https://example.com/v1" });
  });

  it("keeps an unsaved edit and shows the error when saving fails", async () => {
    const onSave = vi.fn(async () => { throw new Error("Could not save settings"); });
    const { r } = mount(custom, onSave);
    act(() => r.root.findByProps({ placeholder: "Leave blank to use the chat model name" }).props.onChange({ target: { value: "other-model" } }));
    await submit(r);
    expect(r.root.findByProps({ role: "alert" }).props.children).toBe("Could not save settings");
    expect(r.root.findByProps({ placeholder: "Leave blank to use the chat model name" }).props.value).toBe("other-model");
    expect(r.root.findByProps({ type: "submit" }).props.disabled).toBe(false);
  });
});
