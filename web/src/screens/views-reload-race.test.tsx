// The version-driven reloads in MuseSheet's Daily pane, Onboarding and the avatar studio
// (the three views that share the feed's reload pattern): a slower earlier answer must
// not land over a newer one's view when the server bumps the version twice in a row.
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { setLocaleSetting } from "../i18n";
import type { ConnectionsData, StudioView, UpcomingData } from "../types";
import { AvatarStudioScreen } from "./AvatarStudioScreen";
import { MuseSheet } from "./MuseSheet";
import { Onboarding } from "./Onboarding";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
// the three views' only window use is the studio's mood animation timer and the sheet's
// listeners; the timer never fires in the test and the listeners never arrive
(globalThis as Record<string, unknown>).window = {
  location: { href: "https://console.example/" },
  setTimeout: () => 0,
  clearTimeout: () => undefined,
  setInterval: () => 0,
  clearInterval: () => undefined,
  addEventListener: () => undefined,
  removeEventListener: () => undefined,
};

const store = vi.hoisted(() => ({
  state: {
    profile: { name: "Muse", avatar: "dragon" },
    settings: { llm: { model: "model-a" } },
    connectionsVersion: 0,
    goalsVersion: 0,
    remindersVersion: 0,
    studio: null,
    status: { state: "idle" },
    pendingApprovals: [],
    threads: [],
    hub: null,
  },
  setTab: () => {},
  draft: {},
  toast: vi.fn(),
  refreshSettings: async () => {},
  decide: async () => {},
  openThread: () => {},
  dismissOnboarding: () => {},
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

function textOf(node: ReactTestRenderer | ReactTestRenderer["root"]): string {
  const out: string[] = [];
  const walk = (n: unknown) => {
    if (!n || typeof n !== "object") return;
    const anyNode = n as { children?: unknown[]; props?: { children?: unknown } };
    for (const child of anyNode.children ?? []) {
      if (typeof child === "string") out.push(child);
      else walk(child);
    }
    const propsChildren = anyNode.props?.children;
    if (typeof propsChildren === "string") out.push(propsChildren);
  };
  walk((node as { root: unknown }).root ?? node);
  return out.join(" ");
}

let screen: ReactTestRenderer;
afterEach(() => {
  if (screen) act(() => screen.unmount());
  vi.restoreAllMocks();
});
beforeEach(() => {
  setLocaleSetting("en");
  store.toast.mockClear();
  store.state = {
    ...store.state,
    goalsVersion: 0,
    remindersVersion: 0,
    connectionsVersion: 0,
    settings: { llm: { model: "model-a" } },
    studio: null,
  };
});

const upcoming = (title: string): UpcomingData =>
  ({
    proactive: true,
    proactivity: "default",
    interval_minutes: 30,
    effective_interval_minutes: 30,
    quiet_hours: "",
    quiet_until: null,
    next_pass_at: null,
    queue: [
      { goal_id: "g1", title, category: "other", due: null, overdue: false, next_step: null, progress: { done: 0, total: 3 } },
    ],
    check_ins: [],
    reminders: [],
    triggers: { items: [], available: {}, mail_last_seen_at: null, mail_last_error: null },
    busy: false,
  }) as unknown as UpcomingData;

describe("MuseSheet Daily reload race", () => {
  it("does not report a refresh failure after the Daily pane closes", async () => {
    vi.spyOn(api, "upcoming").mockResolvedValue(upcoming("Loaded goal"));
    await act(async () => { screen = create(createElement(MuseSheet, { open: true, onClose: () => {} })); });
    await act(async () => { screen.root.findByProps({ "aria-label": "Daily" }).props.onClick(); });
    const pending = deferred<UpcomingData>();
    vi.mocked(api.upcoming).mockImplementationOnce(() => pending.promise);
    store.state = { ...store.state, goalsVersion: 1 };
    await act(async () => { screen.update(createElement(MuseSheet, { open: true, onClose: () => {} })); });
    await act(async () => { screen.update(createElement(MuseSheet, { open: false, onClose: () => {} })); });
    await act(async () => { pending.reject(new Error("closed pane")); });
    expect(store.toast).not.toHaveBeenCalled();
  });

  it("a slower earlier upcoming answer does not land over a newer one", async () => {
    const first = deferred<UpcomingData>();
    const second = deferred<UpcomingData>();
    vi.spyOn(api, "upcoming")
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);
    await act(async () => {
      screen = create(createElement(MuseSheet, { open: true, onClose: () => {} }));
    });
    // the pane tabs carry their labels as aria-label, not as text
    const dailyTab = () => screen.root.findAll((n) => n.type === "button" && n.props["aria-label"] === "Daily")[0];
    await act(async () => {
      dailyTab().props.onClick();
    });
    // a finished goal and a neighbouring reminder bump the two versions together
    store.state = { ...store.state, goalsVersion: 1, remindersVersion: 1 };
    await act(async () => {
      screen.update(createElement(MuseSheet, { open: true, onClose: () => {} }));
      dailyTab().props.onClick();
    });
    await act(async () => {
      second.resolve(upcoming("Newer upcoming sentence"));
    });
    expect(textOf(screen)).toContain("Newer upcoming sentence");
    await act(async () => {
      first.resolve(upcoming("Older upcoming sentence"));
    });
    expect(textOf(screen)).toContain("Newer upcoming sentence");
    expect(textOf(screen)).not.toContain("Older upcoming sentence");
    expect(api.upcoming).toHaveBeenCalledTimes(2);
  });
});

describe("Onboarding connections reload race", () => {
  const connections = (model: string): ConnectionsData =>
    ({
      llm: { provider: "cloud", model, base_url: "", tool_mode: "", stream: true, key_source: "config", from_app: true, cloud: true },
      providers: {},
      embeddings: { mode: "auto", model: "" },
      email: { configured: false },
      calendar: { feeds: [] },
      contacts: { sources: [] },
    }) as unknown as ConnectionsData;

  it("ignores an old failure after a newer connection is displayed", async () => {
    const first = deferred<ConnectionsData>();
    vi.spyOn(api, "connections").mockImplementationOnce(() => first.promise).mockResolvedValue(connections("selected-model"));
    await act(async () => { screen = create(createElement(Onboarding)); });
    await act(async () => {
      screen.root.findAll((n) => n.type === "button" && textOf(n).includes("Get started"))[0].props.onClick();
    });
    store.state = { ...store.state, connectionsVersion: 1 };
    await act(async () => { screen.update(createElement(Onboarding)); });
    await act(async () => { first.reject(new Error("older connection failure")); });
    expect(textOf(screen)).toContain("selected-model");
    expect(textOf(screen)).not.toContain("older connection failure");
  });

  it("a slower earlier connections answer does not land over a newer one", async () => {
    const first = deferred<ConnectionsData>();
    const second = deferred<ConnectionsData>();
    vi.spyOn(api, "connections")
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);
    await act(async () => {
      screen = create(createElement(Onboarding));
    });
    // the checklist with the model line is the step after the welcome one
    await act(async () => {
      screen.root.findAll((n) => n.type === "button" && textOf(n).includes("Get started"))[0].props.onClick();
    });
    store.state = { ...store.state, connectionsVersion: 1 };
    await act(async () => {
      screen.update(createElement(Onboarding));
    });
    await act(async () => {
      second.resolve(connections("newer-conn-model"));
    });
    expect(textOf(screen)).toContain("newer-conn-model");
    await act(async () => {
      first.resolve(connections("older-conn-model"));
    });
    expect(textOf(screen)).toContain("newer-conn-model");
    expect(textOf(screen)).not.toContain("older-conn-model");
    expect(api.connections).toHaveBeenCalledTimes(2);
  });
});

describe("avatar studio reload race", () => {
  const view = (model: string): StudioView =>
    ({ available: true, image_model: model, video_model: "", cloud: false, host: "", current: null, face: null }) as StudioView;

  it("keeps the loaded view on errors and ignores failures after leaving", async () => {
    vi.spyOn(api, "avatarView").mockResolvedValue(view("loaded-model"));
    await act(async () => { screen = create(createElement(AvatarStudioScreen)); });
    vi.mocked(api.avatarView).mockRejectedValueOnce(new Error("refresh failed"));
    store.state = { ...store.state, connectionsVersion: 1 };
    await act(async () => { screen.update(createElement(AvatarStudioScreen)); });
    expect(textOf(screen)).toContain("loaded-model");
    expect(store.toast).toHaveBeenCalledWith("refresh failed");
    const pending = deferred<StudioView>();
    vi.mocked(api.avatarView).mockImplementationOnce(() => pending.promise);
    store.state = { ...store.state, connectionsVersion: 2 };
    await act(async () => { screen.update(createElement(AvatarStudioScreen)); });
    act(() => screen.unmount());
    await act(async () => { pending.reject(new Error("left studio")); });
    expect(store.toast).toHaveBeenCalledTimes(1);
  });

  it("keeps a choice on refresh but clears it for another candidate session", async () => {
    const candidates = (session: string): StudioView => ({
      ...view("image-model"),
      current: { session, stage: "choose", description: "A drawn animal", candidates: [`avatar/${session}/candidate.png`] },
    });
    vi.spyOn(api, "avatarView").mockResolvedValue(candidates("first"));
    await act(async () => { screen = create(createElement(AvatarStudioScreen)); });
    const candidate = () => screen.root.findByProps({ "aria-label": "Candidate 1" });
    act(() => candidate().props.onClick());
    expect(candidate().props["aria-pressed"]).toBe(true);
    store.state = { ...store.state, connectionsVersion: 1 };
    await act(async () => { screen.update(createElement(AvatarStudioScreen)); });
    expect(candidate().props["aria-pressed"]).toBe(true);
    vi.mocked(api.avatarView).mockResolvedValue(candidates("second"));
    store.state = { ...store.state, connectionsVersion: 2 };
    await act(async () => { screen.update(createElement(AvatarStudioScreen)); });
    expect(candidate().props["aria-pressed"]).toBe(false);
    expect(textOf(screen)).not.toContain("Use this one");
  });

  it("a slower earlier studio answer does not land over a newer one", async () => {
    const first = deferred<StudioView>();
    const second = deferred<StudioView>();
    vi.spyOn(api, "avatarView")
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);
    await act(async () => {
      screen = create(createElement(AvatarStudioScreen));
    });
    act(() => screen.root.findByProps({ "aria-label": "Describe a new look" }).props.onChange({ target: { value: "My unfinished description" } }));
    // the model and the connections can both move while a view is on its way
    store.state = { ...store.state, settings: { llm: { model: "model-b" } } };
    await act(async () => {
      screen.update(createElement(AvatarStudioScreen));
    });
    await act(async () => {
      second.resolve(view("newer-image-model"));
    });
    expect(textOf(screen)).toContain("newer-image-model");
    await act(async () => {
      first.resolve(view("older-image-model"));
    });
    expect(textOf(screen)).toContain("newer-image-model");
    expect(textOf(screen)).not.toContain("older-image-model");
    expect(screen.root.findByProps({ "aria-label": "Describe a new look" }).props.value).toBe("My unfinished description");
    expect(api.avatarView).toHaveBeenCalledTimes(2);
  });
});
