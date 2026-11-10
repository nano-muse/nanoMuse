import { act } from "react";
import { create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { setLocaleSetting } from "../i18n";
import type { AuditEntry } from "../types";
import { SentinelReviewRow } from "./SentinelReviewRow";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
const mounted: ReactTestRenderer[] = [];
const entry: AuditEntry = {
  ts: "2026-10-31T12:00:00Z", event: "sentinel_review", status: "ok",
  tool: "calendar__create_event", actual_decision: "ask", recommendation: "allow",
  provider: "openai", model: "review-model", reason: "model_observation",
};

function render(value: AuditEntry) {
  let r!: ReactTestRenderer;
  act(() => { r = create(<SentinelReviewRow entry={value} />); });
  mounted.push(r);
  return JSON.stringify(r.toJSON());
}

beforeEach(() => setLocaleSetting("en"));
afterEach(() => { act(() => mounted.splice(0).forEach((r) => r.unmount())); });

describe("review observations in the audit log", () => {
  it("keeps a model's allow suggestion distinct from the permission decision to ask", () => {
    const text = render(entry);
    expect(text).toContain("Model suggestion: Allow");
    expect(text).toContain("Permission decision: Ask for approval");
    expect(text).toContain("Observation only. The permission decision was not changed.");
    expect(text).toContain("calendar__create_event");
    expect(text).toContain("openai / review-model");
  });

  it("shows a timeout without presenting a suggestion or changing the actual denial", () => {
    const text = render({ ...entry, status: "timeout", recommendation: undefined, actual_decision: "deny", error: "raw provider output" });
    expect(text).toContain("Review timed out");
    expect(text).toContain("Permission decision: Deny");
    expect(text).not.toContain("Model suggestion:");
    expect(text).not.toContain("raw provider output");
  });

  it("explains incomplete input and translates the result", () => {
    setLocaleSetting("zh-CN");
    const text = render({ ...entry, recommendation: "ask", reason: "incomplete_input" });
    expect(text).toContain("模型建议：请求确认");
    expect(text).toContain("本次审核缺少部分操作或任务信息。");
    expect(text).toContain("仅供观察，未改变权限决定。");
  });

  it("distinguishes a configuration change from turning observation off", () => {
    const text = render({ ...entry, status: "disabled", reason: "configuration_changed", recommendation: undefined });
    expect(text).toContain("Review skipped because the configuration changed before it started");
    expect(text).not.toContain("observation was turned off");
  });
});
