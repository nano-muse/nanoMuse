import { createElement } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { setLocaleSetting } from "../i18n";
import type { SkillInfo, SkillsData } from "../types";
import { SkillsScreen } from "./SkillsScreen";

const store = vi.hoisted(() => ({
  state: { profile: null as null, skillsVersion: 0 },
  toast: () => {},
  setTab: () => {},
}));
vi.mock("../store", () => ({ useStore: () => store }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
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
  setLocaleSetting("en");
  vi.spyOn(api, "skills").mockResolvedValue(skillsData([]));
});

afterEach(() => {
  if (screen) act(() => screen.unmount());
  setLocaleSetting("en");
  vi.restoreAllMocks();
});

describe("SkillsScreen reload race", () => {
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
