import { createElement } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { LoadError } from "../components/LoadError";
import { setLocaleSetting } from "../i18n";
import type { CalendarData, FeedItem, FeedPostsData, UpcomingData } from "../types";
import { FeedScreen } from "./FeedScreen";

const store = vi.hoisted(() => ({
  state: {
    profile: null, status: { state: "idle", detail: "", thread: "main" }, settings: null,
    feedVersion: 0, remindersVersion: 0, calendarVersion: 0, connectionsVersion: 0,
    feedSeenAt: "", pendingApprovals: [], loaded: true, connected: true,
    mishapAt: 0, finishedAt: 0, holds: [], working: {},
  },
  markFeedSeen: () => {}, toast: () => {}, setTab: () => {}, setDrawer: () => {},
  draft: vi.fn(), openGoal: vi.fn(), send: async () => {}, openThread: vi.fn(), openFile: () => {},
}));
vi.mock("../store", () => ({ useStore: () => store }));

const activity: FeedItem[] = [{
  id: "activity", ts: "2026-10-14T08:00:00Z", kind: "background",
  title: "Retained activity", text: "Completed work", thread: "main", thread_title: "Main chat",
}];
const posts: FeedPostsData = {
  instructions: "", daily: false, time: "08:00", generated_at: null,
  posts: [{ id: "post", ts: "2026-10-14T08:00:00Z", title: "Retained post", body: "A useful update", area: "other", prompt: "" }],
};
const upcoming: UpcomingData = {
  proactive: false, proactivity: "off", interval_minutes: 60, effective_interval_minutes: 60,
  quiet_hours: "", quiet_until: null, next_pass_at: null, queue: [], check_ins: [], reminders: [], busy: false,
  triggers: { items: [], available: { mail: false, event: false, hook: true, device: false }, mail_checked_at: null, mail_error: "", mail_poll_minutes: 5 },
};
const calendar: CalendarData = {
  enabled: true, configured: false, today: "2026-10-14", events: [], feeds: [], fetched_at: null, stale: false,
};
const owners = ["feed", "feedPosts", "upcoming", "calendar"] as const;
let screen: ReactTestRenderer;

beforeEach(() => {
  setLocaleSetting("en");
  store.state.feedVersion = 0;
  store.state.calendarVersion = 0;
  vi.spyOn(api, "feed").mockResolvedValue(activity);
  vi.spyOn(api, "feedPosts").mockResolvedValue(posts);
  vi.spyOn(api, "upcoming").mockResolvedValue(upcoming);
  vi.spyOn(api, "calendar").mockResolvedValue(calendar);
});

afterEach(() => {
  if (screen) act(() => screen.unmount());
  vi.restoreAllMocks();
});

async function mount() {
  await act(async () => { screen = create(createElement(FeedScreen)); });
}

function failure(message: string) {
  return screen.root.findAllByType(LoadError).find((node) => node.props.message === message);
}

describe("Feed request recovery", () => {
  it.each(owners)("shows a failed %s request and retries only that request", async (owner) => {
    vi.mocked(api[owner]).mockRejectedValueOnce(new Error(`${owner} unavailable`));
    await mount();

    const error = failure(`${owner} unavailable`);
    expect(error, "the failed section must offer a retry").toBeDefined();
    const before = owners.map((name) => vi.mocked(api[name]).mock.calls.length);
    await act(async () => { error!.findByType("button").props.onClick(); });

    expect(failure(`${owner} unavailable`)).toBeUndefined();
    expect(JSON.stringify(screen.toJSON())).toContain("Retained activity");
    expect(JSON.stringify(screen.toJSON())).toContain("Retained post");
    owners.forEach((name, index) => {
      expect(vi.mocked(api[name]).mock.calls.length, name).toBe(before[index] + (name === owner ? 1 : 0));
    });
  });

  it("shows refresh failures alongside the last successful posts and activity", async () => {
    await mount();
    vi.mocked(api.feedPosts).mockRejectedValueOnce(new Error("posts refresh failed"));
    vi.mocked(api.upcoming).mockRejectedValueOnce(new Error("upcoming refresh failed"));
    vi.mocked(api.calendar).mockRejectedValueOnce(new Error("calendar refresh failed"));

    await act(async () => {
      store.state.feedVersion += 1;
      store.state.calendarVersion += 1;
      screen.update(createElement(FeedScreen));
    });

    for (const message of ["posts refresh failed", "upcoming refresh failed", "calendar refresh failed"]) {
      expect(failure(message), message).toBeDefined();
    }
    expect(JSON.stringify(screen.toJSON())).toContain("Retained post");
    expect(JSON.stringify(screen.toJSON())).toContain("Retained activity");
  });

  it.each(["resolve", "reject"] as const)("ignores an older request that finishes with %s after a newer version", async (outcome) => {
    let resolveOld!: (value: FeedPostsData) => void;
    let rejectOld!: (reason: Error) => void;
    vi.mocked(api.feedPosts).mockImplementationOnce(() => new Promise((resolve, reject) => {
      resolveOld = resolve;
      rejectOld = reject;
    }));
    await mount();
    await act(async () => {
      store.state.feedVersion += 1;
      screen.update(createElement(FeedScreen));
    });
    expect(JSON.stringify(screen.toJSON())).toContain("Retained post");

    await act(async () => {
      if (outcome === "resolve") resolveOld({ ...posts, posts: [{ ...posts.posts[0], title: "Obsolete post" }] });
      else rejectOld(new Error("obsolete request failed"));
    });
    expect(JSON.stringify(screen.toJSON())).toContain("Retained post");
    expect(JSON.stringify(screen.toJSON())).not.toContain("Obsolete post");
    expect(failure("obsolete request failed")).toBeUndefined();
  });
});

it("opens the exact deadline, prepares an unsent calendar question and snoozes only the selected card", async () => {
  const withCards: UpcomingData = { ...upcoming, proactive: true, proactivity: "default", followups: [
    { id: "deadline", kind: "goal", goal_id: "goal-42", title: "Review draft", due: "2026-10-14", days_until: 0, next_step: "Proofread" },
    { id: "conflict", kind: "overlap", titles: ["Studio", "Practice"], start: "2026-10-14T09:15:00Z", end: "2026-10-14T10:00:00Z" },
  ] };
  vi.mocked(api.upcoming).mockResolvedValue(withCards);
  vi.spyOn(api, "hideFeedFollowup").mockResolvedValue({ ok: true });
  await mount();
  const card = (label: string) => screen.root.findByProps({ "aria-label": label });
  const click = async (label: string, buttonText: string) => {
    const button = card(label).findAllByType("button").find((b) => b.children.join("") === buttonText);
    await act(async () => { button!.props.onClick(); });
  };
  await click("Due today", "Review goal");
  expect(store.openGoal).toHaveBeenCalledWith("goal-42");
  await click("Calendar overlap", "Discuss overlap");
  expect(store.openThread).toHaveBeenCalledWith("main");
  expect(store.draft).toHaveBeenCalledWith("Help me plan around the overlap between Studio and Practice.");
  vi.mocked(api.upcoming).mockResolvedValue({ ...withCards, followups: withCards.followups!.slice(1) });
  await click("Due today", "Remind me tomorrow");
  expect(api.hideFeedFollowup).toHaveBeenCalledWith("deadline", "tomorrow");
  expect(screen.root.findAllByProps({ "aria-label": "Due today" })).toHaveLength(0);
  expect(card("Calendar overlap")).toBeDefined();
});

it("shows the recorded reason for a plan review and honors the Feed preference", async () => {
  const item = { kind: "review", id: "proposal", goal_id: "goal-7", reason: "proposal", title: "Slides",
    detail: "Use the available figures", note: "", observed_on: "2026-10-14" } as const;
  vi.mocked(api.upcoming).mockResolvedValue({ ...upcoming, proactive: true, followups: [item] });
  await mount();
  const review = screen.root.findByProps({ "aria-label": "Plan change to review" });
  expect(review.findAllByType("p").map((el) => el.children.join(""))).toContain("Use the available figures");
  await act(async () => { review.findAllByType("button")[0].props.onClick(); });
  expect(store.openGoal).toHaveBeenCalledWith("goal-7");
  vi.mocked(api.feedPosts).mockResolvedValue({ ...posts, followups_enabled: false });
  await act(async () => { store.state.feedVersion++; screen.update(createElement(FeedScreen)); });
  expect(screen.root.findAllByProps({ "aria-label": "Plan change to review" })).toHaveLength(0);
});

it("shows verified excerpts, opens the prepared draft and remembers a handled matter", async () => {
  const prep = { ...posts.posts[0], form: "draft" as const, body: "An editable note",
    why_now: "Tomorrow is the review", sources: [{ kind: "goal" as const, quote: "Prepare the review" }] };
  vi.mocked(api.feedPosts).mockResolvedValue({ ...posts, posts: [prep] });
  vi.spyOn(api, "handlePreparation").mockResolvedValue({ ok: true });
  await mount();
  expect(JSON.stringify(screen.toJSON())).toContain("Prepare the review");
  const button = (label: string) => screen.root.findAllByType("button").find((node) => node.children.includes(label));
  await act(async () => { button("Edit draft")!.props.onClick(); });
  expect(store.draft).toHaveBeenCalledWith("An editable note");
  await act(async () => { button("Already handled")!.props.onClick(); });
  expect(api.handlePreparation).toHaveBeenCalledWith(prep.id);
  expect(JSON.stringify(screen.toJSON())).not.toContain("An editable note");
});

it("uses the expected reply to open an unsent follow-up and shows the correction", async () => {
  vi.spyOn(api, "hideFeedFollowup").mockResolvedValue({ ok: true });
  const waiting = { kind: "waiting" as const, id: "wait_42", quote: "I am waiting for the Atlas quote today.",
    due: "2026-11-25", subject: "the Atlas quote", sender: "the supplier", time: "15:30", correction: "Moved to Wednesday." };
  vi.mocked(api.upcoming).mockResolvedValue({ ...upcoming, proactive: true, waiting_followup: waiting });
  await mount();
  const card = screen.root.findByProps({ "aria-label": "You were waiting for a reply" });
  expect(JSON.stringify(screen.toJSON())).toContain(waiting.correction);
  expect(JSON.stringify(screen.toJSON())).toContain("Expected from the supplier by 2026-11-25 15:30");
  const click = async (label: string) => {
    const button = card.findAllByType("button").find((b) => b.children.join("") === label);
    await act(async () => { await button!.props.onClick(); });
  };
  await click("Edit follow-up message");
  expect(store.openThread).toHaveBeenCalledWith("main");
  expect(store.draft).toHaveBeenCalledWith("Hi, do you have an update on the Atlas quote?");
  vi.mocked(api.upcoming).mockResolvedValue(upcoming);
  await click("Dismiss");
  expect(api.hideFeedFollowup).toHaveBeenCalledWith(waiting.id, "dismiss");
  expect(screen.root.findAllByProps({ "aria-label": "You were waiting for a reply" })).toHaveLength(0);
});
