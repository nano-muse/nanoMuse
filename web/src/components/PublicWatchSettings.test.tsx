import { act } from "react";
import { create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setLocaleSetting } from "../i18n";
import type { PublicWatch, PublicWatchView } from "../types";
import { PublicWatchSettings } from "./PublicWatchSettings";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
const fetchMock = vi.fn<typeof fetch>();
const repo: PublicWatch = {
  id: "repo", kind: "github_repo", target: "sample/project", label: "sample/project",
  status: "suggested", last_checked: null, unavailable: false,
};
let render: ReactTestRenderer;

function reply(revision: string, watches: PublicWatch[], enabled = true) {
  const view: PublicWatchView = { enabled, revision, watches };
  fetchMock.mockResolvedValueOnce(Response.json(view));
}

async function open() {
  await act(async () => { render = create(<PublicWatchSettings />); });
}

function button(text: string, group: ReactTestInstance = render.root) {
  return group.findAllByType("button").find(b => b.children.includes(text))!;
}

async function click(text: string) {
  await act(async () => { button(text).props.onClick(); });
}

function sent(i: number) {
  const [path, options] = fetchMock.mock.calls[i];
  return [path, options?.method, JSON.parse(String(options?.body))];
}

beforeEach(() => {
  setLocaleSetting("en");
  vi.stubGlobal("window", { location: new URL("https://example.org/") });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  act(() => render?.unmount());
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

describe("public source settings", () => {
  it("changes cross-device delivery without changing which sources are followed", async () => {
    const initial = { enabled: true, revision: "a", can_share: true, share_public_updates: false, watches: [] };
    fetchMock.mockResolvedValueOnce(Response.json(initial));
    await open();
    const toggle = render.root.findAllByProps({ role: "switch" })[1];
    expect(toggle.props["aria-checked"]).toBe(false);
    fetchMock.mockResolvedValueOnce(Response.json({ ...initial, revision: "b", share_public_updates: true }));
    await act(async () => { toggle.props.onClick(); });
    expect(sent(1)).toEqual(["/api/feed/watches", "PUT", { revision: "a", share_public_updates: true }]);
    expect(render.root.findAllByProps({ role: "switch" })[1].props["aria-checked"]).toBe(true);
  });

  it("keeps suggestions local until followed, then offers pause, resume and permanent dismissal", async () => {
    reply("r1", [repo]);
    await open();
    expect(fetchMock.mock.calls.map(call => call[0])).toEqual(["/api/feed/watches"]);
    expect(button("Don’t suggest again")).toBeDefined();

    const active: PublicWatch = { ...repo, status: "active" };
    reply("r2", [active]);
    await click("Follow source");
    expect(sent(1)).toEqual(["/api/feed/watches/repo", "PATCH", { revision: "r1", action: "confirm" }]);
    reply("r3", [{ ...repo, status: "paused" }]);
    await click("Pause");
    expect(sent(2)).toEqual(["/api/feed/watches/repo", "PATCH", { revision: "r2", action: "pause" }]);
    reply("r4", [active]);
    await click("Resume");
    expect(sent(3)).toEqual(["/api/feed/watches/repo", "PATCH", { revision: "r3", action: "resume" }]);
    reply("r5", []);
    await click("Stop following");
    expect(sent(4)).toEqual(["/api/feed/watches/repo", "PATCH", { revision: "r4", action: "dismiss" }]);
    expect(render.root.findAllByProps({ role: "group" })).toHaveLength(0);
  });

  it("links a Scholar suggestion only after the reader supplies a matching identifier", async () => {
    reply("r1", [{ ...repo, id: "scholar", kind: "scholar_profile", target: "profile-id" }]);
    await open();
    expect(button("Follow source")).toBeUndefined();
    await click("Link author or paper");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(render.root.findAllByType("option").map(o => o.props.value)).toEqual(["research_author", "research_work"]);
    expect(button("Link and follow").props.disabled).toBe(true);
    act(() => render.root.findByType("select").props.onChange({ target: { value: "research_work" } }));
    act(() => render.root.findByType("input").props.onChange({ target: { value: "  10.0000/article  " } }));
    reply("r2", []);
    await act(async () => { render.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
    expect(sent(1)).toEqual(["/api/feed/watches/scholar", "PATCH", {
      revision: "r1", action: "confirm", kind: "research_work", target: "10.0000/article",
    }]);
  });

  it("preserves an explicit source draft across a stale edit without automatically retrying a write", async () => {
    reply("r1", []);
    await open();
    await click("Add a public source");
    act(() => render.root.findByType("select").props.onChange({ target: { value: "research_topic" } }));
    act(() => render.root.findByType("input").props.onChange({ target: { value: "  diffusion models " } }));
    fetchMock.mockResolvedValueOnce(Response.json({ detail: "Settings changed." }, { status: 409 }));
    reply("r2", []);
    const submit = () => act(async () => { render.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
    await submit();
    expect(sent(1)).toEqual(["/api/feed/watches", "POST", {
      revision: "r1", kind: "research_topic", target: "diffusion models",
    }]);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[2][1]?.method).toBeUndefined();
    expect(render.root.findByType("input").props.value).toBe("  diffusion models ");
    expect(render.root.findByProps({ role: "alert" }).children).toContain("Settings changed.");
    reply("r3", []);
    await submit();
    expect(sent(3)).toEqual(["/api/feed/watches", "POST", {
      revision: "r2", kind: "research_topic", target: "diffusion models",
    }]);
  });

  it("loads the server's master switch and lets the reader suppress a suggestion even when checks are off", async () => {
    reply("r1", [repo], false);
    await open();
    expect(render.root.findByProps({ role: "switch" }).props["aria-checked"]).toBe(false);
    expect(button("Add a public source")).toBeUndefined();
    expect(button("Follow source").props.disabled).toBe(true);
    reply("r2", [], false);
    await click("Don’t suggest again");
    expect(sent(1)).toEqual(["/api/feed/watches/repo", "PATCH", { revision: "r1", action: "dismiss" }]);
    reply("r3", []);
    await act(async () => { render.root.findByProps({ role: "switch" }).props.onClick(); });
    expect(sent(2)).toEqual(["/api/feed/watches", "PUT", { revision: "r2", enabled: true }]);
    expect(button("Add a public source")).toBeDefined();
  });
});
