import { createElement } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { setLocaleSetting } from "../i18n";
import type { SkillInfo, SkillsData } from "../types";
import { SkillsScreen } from "./SkillsScreen";

const store = vi.hoisted(() => ({
  state: { profile: null as null, skillsVersion: 0 },
  toast: vi.fn(),
  setTab: () => {},
}));
vi.mock("../store", () => ({ useStore: () => store }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

const skill = (name: string): SkillInfo => ({
  name,
  description: `What ${name} does`,
  source: "built-in",
  enabled: true,
  path: `skills/${name}`,
  files: [],
  allowed_tools: [],
  metadata: {},
  updated_at: null,
});

const skillsData = (names: string[]): SkillsData => ({
  count: names.length,
  built_in: names.length,
  yours: 0,
  dir: "skills",
  errors: {},
  skills: names.map(skill),
});

let screen: ReactTestRenderer;

function renderedText(): string {
  const walk = (node: unknown): string => {
    if (typeof node === "string") return node;
    if (Array.isArray(node)) return node.map(walk).join(" ");
    if (node && typeof node === "object" && "children" in node) {
      return walk((node as { children: unknown }).children);
    }
    return "";
  };
  return walk(screen.toJSON());
}

beforeEach(() => {
  store.state = { profile: null, skillsVersion: 0 };
  store.toast.mockClear();
  setLocaleSetting("en");
  vi.spyOn(api, "skills").mockResolvedValue(skillsData([]));
});

afterEach(() => {
  if (screen) act(() => screen.unmount());
  setLocaleSetting("en");
  vi.restoreAllMocks();
});

describe("SkillsScreen reload race", () => {
  it("preserves the loaded list when a refresh fails", async () => {
    vi.mocked(api.skills).mockResolvedValueOnce(skillsData(["saved-skill"]));
    await act(async () => { screen = create(createElement(SkillsScreen)); });
    vi.mocked(api.skills).mockRejectedValueOnce(new Error("refresh offline"));
    store.state = { ...store.state, skillsVersion: 1 };
    await act(async () => { screen.update(createElement(SkillsScreen)); });
    expect(renderedText()).toContain("saved-skill");
    expect(store.toast).toHaveBeenCalledWith("refresh offline");
  });

  it("ignores rejected older requests and errors after leaving the page", async () => {
    await act(async () => { screen = create(createElement(SkillsScreen)); });
    const older = deferred<SkillsData>();
    vi.mocked(api.skills).mockImplementationOnce(() => older.promise);
    store.state = { ...store.state, skillsVersion: 1 };
    await act(async () => { screen.update(createElement(SkillsScreen)); });
    store.state = { ...store.state, skillsVersion: 2 };
    await act(async () => { screen.update(createElement(SkillsScreen)); });
    await act(async () => { older.reject(new Error("older failure")); });
    expect(store.toast).not.toHaveBeenCalled();
    const pending = deferred<SkillsData>();
    vi.mocked(api.skills).mockImplementationOnce(() => pending.promise);
    store.state = { ...store.state, skillsVersion: 3 };
    await act(async () => { screen.update(createElement(SkillsScreen)); });
    act(() => screen.unmount());
    await act(async () => { pending.reject(new Error("left page")); });
    expect(store.toast).not.toHaveBeenCalled();
  });

  it("a slower earlier answer does not land over a newer one", async () => {
    // saving a skill bumps the version while the first load is still on its way
    const first = deferred<SkillsData>();
    const second = deferred<SkillsData>();
    vi.mocked(api.skills)
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);
    await act(async () => {
      screen = create(createElement(SkillsScreen));
    });
    store.state = { ...store.state, skillsVersion: 1 };
    await act(async () => {
      screen.update(createElement(SkillsScreen));
    });
    await act(async () => {
      second.resolve(skillsData(["fresh-skill"]));
    });
    expect(renderedText()).toContain("fresh-skill");
    await act(async () => {
      first.resolve(skillsData(["stale-skill"]));
    });
    expect(renderedText()).toContain("fresh-skill");
    expect(renderedText()).not.toContain("stale-skill");
    expect(api.skills).toHaveBeenCalledTimes(2);
  });
});
