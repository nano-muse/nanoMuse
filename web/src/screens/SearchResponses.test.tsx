import type { ReactNode } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { setLocaleSetting } from "../i18n";
import type { CodingAgent, CodingSession, ConnectionsData, Contact } from "../types";
import { NewChatSheet } from "./CodingScreen";
import { ContactsCard } from "./ConnectionsScreen";

vi.mock("../store", () => ({ useStore: () => ({ toast: () => {} }) }));
vi.mock("../components/Sheet", () => ({ Sheet: ({ children }: { children: ReactNode }) => <div>{children}</div> }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
let screen: ReactTestRenderer | undefined;
const text = () => JSON.stringify(screen!.toJSON());
const contact = (name: string): Contact => ({
  id: name, name, first: "", last: "", nickname: "", emails: [], phones: [], org: "", title: "",
  birthday: "", addresses: [], urls: [], note: "", source: "",
});
const contacts = { contacts: { enabled: true, configured: true, count: 0, own: 0, sources: [] } } as unknown as ConnectionsData;
const agents: CodingAgent[] = ["cursor", "codex"].map((id) => ({
  id, name: id, installed: true, cli: null, version: "", sessions_root: "", running: 0,
}));
const sessions = (workspace: string) => ({ sessions: [{ workspace } as CodingSession] });
const sheet = (device = "first-device") => <NewChatSheet agent="cursor" agents={agents} device={device} onClose={() => {}} onStarted={() => {}} />;

beforeEach(() => {
  setLocaleSetting("en");
  vi.useFakeTimers();
});
afterEach(() => {
  if (screen) act(() => screen!.unmount());
  screen = undefined;
  vi.restoreAllMocks();
  vi.useRealTimers();
});

async function query(value: string) {
  act(() => { screen!.root.findByProps({ "aria-label": "Find someone, as the agent would" }).props.onChange({ target: { value } }); });
  await act(async () => { await vi.advanceTimersByTimeAsync(250); });
}

describe("contact search responses", () => {
  for (const outcome of ["success", "error"] as const) {
    it(`ignores an earlier query's late ${outcome}`, async () => {
      const old = deferred<Awaited<ReturnType<typeof api.contacts>>>();
      vi.spyOn(api, "contacts").mockReturnValueOnce(old.promise).mockResolvedValueOnce({ count: 1, people: [contact("current-result")] });
      await act(async () => { screen = create(<ContactsCard data={contacts} onChange={() => {}} compact />); });
      await query("old");
      await query("current");
      await act(async () => {
        if (outcome === "success") old.resolve({ count: 1, people: [contact("obsolete-result")] });
        else old.reject(new Error("obsolete error"));
      });
      expect(text()).toContain("current-result");
      expect(text()).not.toContain("obsolete-result");
    });
  }

  it("clears visible hits when the query changes and drops a response after clearing", async () => {
    const late = deferred<Awaited<ReturnType<typeof api.contacts>>>();
    vi.spyOn(api, "contacts").mockResolvedValueOnce({ count: 1, people: [contact("previous-result")] }).mockReturnValueOnce(late.promise);
    await act(async () => { screen = create(<ContactsCard data={contacts} onChange={() => {}} compact />); });
    await query("first");
    expect(text()).toContain("previous-result");
    await query("second");
    expect(text()).not.toContain("previous-result");
    await query("");
    await act(async () => { late.resolve({ count: 1, people: [contact("late-result")] }); });
    expect(text()).not.toContain("late-result");
  });
});

describe("recent coding workspaces", () => {
  for (const outcome of ["success", "error"] as const) {
    it(`ignores an earlier device's late ${outcome}`, async () => {
      const old = deferred<Awaited<ReturnType<typeof api.codingSessions>>>();
      vi.spyOn(api, "codingSessions").mockReturnValueOnce(old.promise).mockResolvedValueOnce(sessions("/projects/current-workspace"));
      await act(async () => { screen = create(sheet()); });
      await act(async () => { screen!.update(sheet("second-device")); });
      await act(async () => {
        if (outcome === "success") old.resolve(sessions("/projects/obsolete-workspace"));
        else old.reject(new Error("obsolete device error"));
      });
      expect(text()).toContain("current-workspace");
      expect(text()).not.toContain("obsolete-workspace");
    });
  }

  it("clears recent workspaces when the agent changes", async () => {
    const next = deferred<Awaited<ReturnType<typeof api.codingSessions>>>();
    vi.spyOn(api, "codingSessions").mockResolvedValueOnce(sessions("/projects/previous-workspace")).mockReturnValueOnce(next.promise);
    await act(async () => { screen = create(sheet()); });
    expect(text()).toContain("previous-workspace");
    const button = screen!.root.findAllByType("button").find((node) => Array.isArray(node.props.children) && node.props.children.includes("Codex"));
    act(() => { button!.props.onClick(); });
    expect(text()).not.toContain("previous-workspace");
    expect(api.codingSessions).toHaveBeenLastCalledWith({ agent: "codex", device: "first-device", limit: 30 });
    await act(async () => { next.resolve(sessions("/projects/new-workspace")); });
    expect(text()).toContain("new-workspace");
  });
});
