import { act } from "react";
import { create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, beforeAll, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { setLocaleSetting } from "../i18n";
import type { SkillInfo, SkillsData } from "../types";
import { Composer, WorkingLine } from "./ChatScreen";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
// the composer's only window use is the quick-chat focus listener
(globalThis as Record<string, unknown>).window = {
  addEventListener: () => undefined,
  removeEventListener: () => undefined,
};

const store = vi.hoisted(() => ({
  state: {
    draft: null,
    draftFiles: null,
    settings: { skills: { enabled: false } },
    hub: null,
    skillsVersion: 0,
  },
  draft: () => undefined,
  draftFiles: () => undefined,
  toast: () => undefined,
}));
vi.mock("../store", () => ({ useStore: () => store }));

function discs(r: ReactTestRenderer) {
  return {
    stop: r.root.findAllByProps({ "aria-label": "Stop" })[0],
    send: r.root.findAllByProps({ "aria-label": "Send" })[0],
  };
}

describe("Composer stop disc", () => {
  // the labels looked for are the English ones, whatever the machine running the suite speaks
  beforeAll(() => setLocaleSetting("en"));

  it("swaps the send disc for a stop disc while busy with an empty box", () => {
    let r!: ReactTestRenderer;
    act(() => {
      r = create(<Composer name="Muse" busy waiting={false} onSend={vi.fn(async () => undefined)} onStop={vi.fn(async () => undefined)} />);
    });
    const d = discs(r);
    expect(d.stop).toBeDefined();
    expect(d.send).toBeUndefined();
  });

  it("keeps no stop disc without an onStop", () => {
    let r!: ReactTestRenderer;
    act(() => {
      r = create(<Composer name="Muse" busy waiting={false} onSend={vi.fn(async () => undefined)} />);
    });
    const d = discs(r);
    expect(d.stop).toBeUndefined();
    expect(d.send).toBeDefined();
    expect(d.send?.props.disabled).toBe(true);
  });

  it("brings the send disc back once there is text", async () => {
    let r!: ReactTestRenderer;
    act(() => {
      r = create(<Composer name="Muse" busy waiting={false} onSend={vi.fn(async () => undefined)} onStop={vi.fn(async () => undefined)} />);
    });
    const box = r.root.findByProps({ "aria-label": "Message" });
    await act(async () => {
      box.props.onChange({ target: { value: "接着来" } });
    });
    const d = discs(r);
    expect(d.stop).toBeUndefined();
    expect(d.send).toBeDefined();
    expect(d.send?.props.disabled).toBe(false);
  });

  it("calls onStop once and holds the disc while the stop is under way", async () => {
    const onStop = vi.fn(() => new Promise<void>(() => undefined));
    let r!: ReactTestRenderer;
    act(() => {
      r = create(<Composer name="Muse" busy waiting={false} onSend={vi.fn(async () => undefined)} onStop={onStop} />);
    });
    const disc = discs(r).stop;
    await act(async () => {
      disc.props.onClick();
    });
    expect(onStop).toHaveBeenCalledTimes(1);
    expect(discs(r).stop?.props.disabled).toBe(true);
  });
});

// The presence frame from another device says what its run is doing — the line
// under the message reads the step, and a run parked on a card reads as waiting.

function line(who: Parameters<typeof WorkingLine>[0]["who"]) {
  let r!: ReactTestRenderer;
  act(() => {
    r = create(<WorkingLine who={who} />);
  });
  return r.root.findByType("div").props.children[1].props.children;
}

describe("WorkingLine", () => {
  beforeAll(() => setLocaleSetting("en"));

  it("reads as plain working without a state", () => {
    expect(line({ thread: "main", cid: "c", device: "phone-1", device_name: "Pixel 8", at: 1 })).toBe(
      "Pixel 8 is working…",
    );
  });

  it("reads the step the run reported", () => {
    expect(
      line({ thread: "main", cid: "c", device: "phone-1", device_name: "Pixel 8", state: "working", detail: "打开携程网站", at: 1 }),
    ).toBe("Pixel 8 is working: 打开携程网站");
  });

  it("reads as waiting when the run is parked on a card", () => {
    expect(
      line({ thread: "main", cid: "c", device: "phone-1", device_name: "", state: "waiting", at: 1 }),
    ).toBe("phone-1 is waiting for you");
  });
});

// The "/" menu lists the skills; its refresh rides the version the server bumps on
// every save, so two answers can be in flight at once and a refresh can also fail.

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

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function allText(r: ReactTestRenderer): string {
  const walk = (node: unknown): string => {
    if (typeof node === "string") return node;
    if (Array.isArray(node)) return node.map(walk).join(" ");
    if (node && typeof node === "object" && "children" in node) {
      return walk((node as { children: unknown }).children);
    }
    return "";
  };
  return walk(r.toJSON());
}

async function menuAfterTyping(r: ReactTestRenderer, value: string) {
  const box = r.root.findByProps({ "aria-label": "Message" });
  await act(async () => {
    box.props.onChange({ target: { value } });
  });
  return allText(r);
}

describe("Composer slash menu skills", () => {
  beforeEach(() => {
    setLocaleSetting("en");
    store.state = {
      ...store.state,
      settings: { skills: { enabled: true } },
      skillsVersion: 0,
    };
  });

  afterEach(() => {
    store.state = {
      ...store.state,
      settings: { skills: { enabled: false } },
      skillsVersion: 0,
    };
    vi.restoreAllMocks();
  });

  it("a slower earlier answer does not land over a newer one", async () => {
    const first = deferred<SkillsData>();
    const second = deferred<SkillsData>();
    vi.spyOn(api, "skills")
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);
    let r!: ReactTestRenderer;
    act(() => {
      r = create(<Composer name="Muse" busy={false} waiting={false} onSend={vi.fn(async () => undefined)} />);
    });
    store.state = { ...store.state, skillsVersion: 1 };
    await act(async () => {
      r.update(<Composer name="Muse" busy={false} waiting={false} onSend={vi.fn(async () => undefined)} />);
    });
    await act(async () => {
      second.resolve(skillsData(["fresh-skill"]));
    });
    expect(await menuAfterTyping(r, "/")).toContain("fresh-skill");
    await act(async () => {
      first.resolve(skillsData(["stale-skill"]));
    });
    const text = await menuAfterTyping(r, "/");
    expect(text).toContain("fresh-skill");
    expect(text).not.toContain("stale-skill");
    expect(api.skills).toHaveBeenCalledTimes(2);
  });

  it("keeps its list when a refresh fails", async () => {
    vi.spyOn(api, "skills")
      .mockResolvedValueOnce(skillsData(["kept-skill"]))
      .mockRejectedValueOnce(new Error("offline"));
    let r!: ReactTestRenderer;
    act(() => {
      r = create(<Composer name="Muse" busy={false} waiting={false} onSend={vi.fn(async () => undefined)} />);
    });
    expect(await menuAfterTyping(r, "/")).toContain("kept-skill");
    store.state = { ...store.state, skillsVersion: 1 };
    await act(async () => {
      r.update(<Composer name="Muse" busy={false} waiting={false} onSend={vi.fn(async () => undefined)} />);
    });
    const text = await menuAfterTyping(r, "/");
    expect(text).toContain("kept-skill");
  });
});
