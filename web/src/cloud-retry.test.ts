import { describe, expect, it } from "vitest";
import { cloudRetryTarget } from "./cloud-retry";
import type { TimelineEvent } from "./types";

const user = (id: string, text: string, files?: string[]): TimelineEvent =>
  ({ id, ts: "2026-10-09T00:00:00Z", type: "user", text, ...(files ? { files: files.map((path) => ({ path, name: path, size: 1, kind: "other", mime: "" })) } : {}) }) as TimelineEvent;
const failed = (id: string, extra: Record<string, unknown> = {}): TimelineEvent =>
  ({ id, ts: "2026-10-09T00:00:01Z", type: "notice", level: "error", code: "key", text: "The model provider refused the API key. Check it under Connections.", ...extra }) as TimelineEvent;
const ctx = { signedIn: true, chatOnCloud: false, deviceChat: false };

describe("Use nanoMuse Cloud this time", () => {
  it("offers the words of the failed turn under its notice", () => {
    const events = [user("u1", "first"), failed("n1"), user("u2", "second", ["attachments/a.pdf"]), failed("n2")];
    expect(cloudRetryTarget(events, 1, ctx)).toEqual({ text: "first", files: [] });
    expect(cloudRetryTarget(events, 3, ctx)).toEqual({ text: "second", files: ["attachments/a.pdf"] });
    // not under the user bubble itself, nor an info notice
    expect(cloudRetryTarget(events, 0, ctx)).toBeUndefined();
    expect(cloudRetryTarget([user("u", "x"), { ...failed("n"), level: "info" } as TimelineEvent], 1, ctx)).toBeUndefined();
  });

  it("stays away when the account cannot or need not answer", () => {
    const events = [user("u1", "first"), failed("n1")];
    expect(cloudRetryTarget(events, 1, { ...ctx, signedIn: false })).toBeUndefined();
    expect(cloudRetryTarget(events, 1, { ...ctx, chatOnCloud: true })).toBeUndefined();
    expect(cloudRetryTarget(events, 1, { ...ctx, deviceChat: true })).toBeUndefined();
    // the turn ran on the account already: the notice says which model
    expect(cloudRetryTarget([user("u1", "first"), failed("n1", { model_used: "deepseek-v4.1-flash" })], 1, ctx)).toBeUndefined();
    // the allowance card has its own ways on
    expect(cloudRetryTarget([user("u1", "first"), failed("n1", { code: "allowance" })], 1, ctx)).toBeUndefined();
    // a notice with no user turn above it
    expect(cloudRetryTarget([failed("n1")], 0, ctx)).toBeUndefined();
  });
});
