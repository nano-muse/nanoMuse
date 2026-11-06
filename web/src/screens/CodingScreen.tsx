import { ArrowUp, Bot, ChevronRight, FolderOpen, Loader2, MonitorSmartphone, Plus, RefreshCw, Square, TerminalSquare, Wrench } from "lucide-react";
import { useCallback, useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "../api";
import { PageBar } from "../components/BackBar";
import { MuseRoundButton } from "../components/MuseHeader";
import { inputCls, primaryBtn, secondaryBtn } from "../components/Form";
import { Markdown } from "../components/Markdown";
import { Sheet } from "../components/Sheet";
import { useT } from "../i18n";
import { useStore, type CodingLive } from "../store";
import type { CodingAgent, CodingRun, CodingSession } from "../types";
import { cx, relativeSeconds } from "../util";

const AGENT_META: Record<string, { label: string; tone: string; glyph: string }> = {
  cursor: { label: "Cursor", tone: "from-slate-700 to-slate-900", glyph: "C" },
  codex: { label: "Codex", tone: "from-emerald-500 to-teal-700", glyph: "X" },
  claude: { label: "Claude Code", tone: "from-orange-400 to-amber-600", glyph: "A" },
};

/**
 * Your coding agents — Cursor, Codex, Claude Code — on this computer or on any other of
 * yours that runs nanoMuse: what they are working on, what was said in each chat, and a
 * way to tell them something from wherever you are. The agent works on that computer; the
 * reply streams back here.
 */
export function CodingScreen() {
  const { state, toast } = useStore();
  const t = useT();
  const [device, setDevice] = useState("");
  const [agents, setAgents] = useState<CodingAgent[] | null>(null);
  const [runs, setRuns] = useState<CodingRun[]>([]);
  const [sessions, setSessions] = useState<CodingSession[] | null>(null);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<{ agent: string; id: string } | null>(null);
  const [fresh, setFresh] = useState<string | null>(null); // agent id for a new chat

  const devices = useMemo(
    () => (state.hub?.devices ?? []).filter((d) => !d.this && d.online && d.kind !== "web" && (d.actions ?? []).includes("coding.sessions")),
    [state.hub?.devices],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [a, s] = await Promise.all([api.coding(device), api.codingSessions({ device, limit: 40 })]);
      setAgents(a.agents);
      setRuns(a.runs ?? []);
      setSessions(s.sessions);
    } catch (e) {
      setError((e as Error).message);
      setAgents([]);
      setSessions([]);
    } finally {
      setLoading(false);
    }
  }, [device]);

  useEffect(() => {
    void load();
  }, [load]);

  // a finished run means the transcript on disk changed: refresh quietly
  const liveRuns = Object.values(state.codingLive);
  const finished = liveRuns.filter((l) => l.run.status !== "running").length;
  useEffect(() => {
    if (finished) void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finished]);

  // empty chats (a window opened and closed) are noise unless something is running in them
  const shown = (sessions ?? []).filter((s) => (!filter || s.agent === filter) && (s.messages > 0 || s.status === "running"));
  const installed = (agents ?? []).filter((a) => a.installed);
  const runningIds = new Set(liveRuns.filter((l) => l.run.status === "running" && (l.run.device ?? "") === (device ? deviceName(devices, device) : "")).map((l) => l.run.session_id || l.run.asked_session_id));

  return (
    <div className="flex h-full flex-col">
      <PageBar
        title={t("Coding agents")}
        description={t("Cursor, Codex and Claude Code: see what they are doing, and tell them things from anywhere.")}
        actions={
          <MuseRoundButton small onClick={() => void load()} label={t("Refresh")}>
            <RefreshCw size={18} className={loading ? "animate-spin" : ""} />
          </MuseRoundButton>
        }
      />

      <div className="flex-1 overflow-y-auto px-4 pb-8 space-y-4">
        {/* where */}
        {(devices.length > 0 || device) && (
          <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4">
            <Chip active={!device} onClick={() => setDevice("")} icon={<TerminalSquare size={14} />} label={state.hub?.device?.name ? t("This one · {name}", { name: state.hub.device.name }) : t("This computer")} />
            {devices.map((d) => (
              <Chip key={d.id} active={device === d.id} onClick={() => setDevice(d.id)} icon={<MonitorSmartphone size={14} />} label={d.name} />
            ))}
          </div>
        )}

        {/* agents */}
        {agents && (
          <div className="grid grid-cols-3 gap-2">
            {agents.map((a) => {
              const meta = AGENT_META[a.id];
              return (
                <button
                  key={a.id}
                  type="button"
                  disabled={!a.installed}
                  onClick={() => setFilter((f) => (f === a.id ? "" : a.id))}
                  className={cx("rounded-3xl border p-3 text-left transition", filter === a.id ? "border-accent/40 bg-accent/5" : "border-border/70 bg-surface", !a.installed && "opacity-45")}
                >
                  <div className="flex items-center justify-between">
                    <AgentGlyph agent={a.id} size={30} />
                    {a.running > 0 && (
                      <span className="flex items-center gap-1 rounded-full bg-emerald-500/12 px-1.5 py-0.5 text-[10.5px] font-semibold text-emerald-700 dark:text-emerald-300">
                        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" /> {a.running}
                      </span>
                    )}
                  </div>
                  <div className="mt-2 truncate text-[13.5px] font-semibold">{meta?.label ?? a.name}</div>
                  <div className="truncate text-[11.5px] text-muted">{a.installed ? (a.cli ? a.version || t("installed") : t("chats only")) : t("not found")}</div>
                </button>
              );
            })}
          </div>
        )}

        {error && <div className="rounded-2xl bg-rose-500/12 px-3 py-2 text-[12.5px] text-rose-700 dark:text-rose-300">{error}</div>}

        {/* live runs */}
        {liveRuns.filter((l) => l.run.status === "running").length > 0 && (
          <section className="space-y-2">
            <h2 className="px-1 text-[12px] font-semibold uppercase tracking-wide text-muted">{t("Working now")}</h2>
            {liveRuns
              .filter((l) => l.run.status === "running")
              .map((l) => (
                <LiveRunCard key={l.run.id} live={l} onOpen={() => setOpen({ agent: l.run.agent, id: l.run.session_id || l.run.asked_session_id || "" })} />
              ))}
          </section>
        )}

        {/* sessions */}
        <section className="space-y-2">
          <div className="flex items-center justify-between px-1">
            <h2 className="text-[12px] font-semibold uppercase tracking-wide text-muted">{filter ? t("{agent} chats", { agent: AGENT_META[filter]?.label ?? filter }) : t("Recent chats")}</h2>
            {installed.some((a) => a.cli) && (
              <button type="button" onClick={() => setFresh(filter && installed.find((a) => a.id === filter && a.cli) ? filter : installed.find((a) => a.cli)?.id ?? null)} className="flex items-center gap-1 text-[12.5px] font-medium text-accent">
                <Plus size={14} /> {t("New chat")}
              </button>
            )}
          </div>
          {sessions === null ? (
            <div className="flex justify-center py-10 text-muted">
              <Loader2 size={20} className="animate-spin" />
            </div>
          ) : shown.length === 0 ? (
            <div className="rounded-3xl border border-dashed border-border/80 px-4 py-8 text-center text-[13.5px] text-muted">
              {agents && agents.every((a) => !a.installed) ? t("No coding agent found on this computer. Install Cursor, Codex or Claude Code and their chats appear here.") : t("No chats yet.")}
            </div>
          ) : (
            <ul className="divide-y divide-border/60 overflow-hidden rounded-3xl border border-border/70 bg-surface">
              {shown.map((s) => (
                <li key={`${s.agent}-${s.id}`}>
                  <button type="button" onClick={() => setOpen({ agent: s.agent, id: s.id })} className="flex w-full items-center gap-3 px-3.5 py-3 text-left hover:bg-surface-2/60 active:bg-surface-2">
                    <AgentGlyph agent={s.agent} size={34} />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="truncate text-[14.5px] font-medium">{s.title || t("Untitled chat")}</span>
                        <StatusPill status={runningIds.has(s.id) ? "running" : s.status} />
                      </span>
                      <span className="mt-0.5 flex items-center gap-1.5 truncate text-[12px] text-muted">
                        {s.workspace && (
                          <span className="flex min-w-0 items-center gap-1">
                            <FolderOpen size={11} /> <span className="truncate">{basename(s.workspace)}</span>
                          </span>
                        )}
                        <span>· {relativeSeconds(s.updated_at)}</span>
                        <span>· {t("{n} messages", { n: s.messages })}</span>
                      </span>
                    </span>
                    <ChevronRight size={16} className="shrink-0 text-muted" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* past runs sent from here */}
        {runs.filter((r) => r.status !== "running").length > 0 && (
          <section className="space-y-2">
            <h2 className="px-1 text-[12px] font-semibold uppercase tracking-wide text-muted">{t("Sent through nanoMuse")}</h2>
            <ul className="divide-y divide-border/60 overflow-hidden rounded-3xl border border-border/70 bg-surface">
              {runs
                .filter((r) => r.status !== "running")
                .slice(0, 8)
                .map((r) => (
                  <li key={r.id} className="flex items-center gap-3 px-3.5 py-2.5">
                    <AgentGlyph agent={r.agent} size={28} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13.5px]">{r.text}</span>
                      <span className="block truncate text-[11.5px] text-muted">
                        {r.status === "done" ? t("done") : r.status === "failed" ? t("failed") : t("stopped")} · {relativeSeconds(r.started_at)}
                        {r.tools ? ` · ${t("{n} steps", { n: r.tools })}` : ""}
                        {r.error ? ` · ${r.error}` : ""}
                      </span>
                    </span>
                    {r.session_id && (
                      <button type="button" onClick={() => setOpen({ agent: r.agent, id: r.session_id })} className="text-[12.5px] font-medium text-accent">
                        {t("Open")}
                      </button>
                    )}
                  </li>
                ))}
            </ul>
          </section>
        )}
      </div>

      {open && <SessionSheet agent={open.agent} id={open.id} device={device} deviceLabel={device ? deviceName(devices, device) : ""} onClose={() => setOpen(null)} />}
      {fresh && (
        <NewChatSheet
          agent={fresh}
          agents={installed.filter((a) => a.cli)}
          device={device}
          onClose={() => setFresh(null)}
          onStarted={(run) => {
            setFresh(null);
            toast(t("Sent to {agent}.", { agent: AGENT_META[run.agent]?.label ?? run.agent }));
          }}
        />
      )}
    </div>
  );
}

// ------------------------------------------------------------------ one chat
function SessionSheet({ agent, id, device, deviceLabel, onClose }: { agent: string; id: string; device: string; deviceLabel: string; onClose: () => void }) {
  const { state, toast } = useStore();
  const t = useT();
  const [session, setSession] = useState<CodingSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const listRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    try {
      setSession(await api.codingSession(agent, id, device));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [agent, id, device]);
  useEffect(() => {
    void load();
  }, [load]);

  // runs on this chat, live
  const live = Object.values(state.codingLive).filter((l) => l.run.agent === agent && (l.run.session_id === id || l.run.asked_session_id === id));
  const running = live.find((l) => l.run.status === "running");
  const lastFinished = live.filter((l) => l.run.status !== "running").length;
  useEffect(() => {
    if (lastFinished) void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastFinished]);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [session?.transcript?.length, running?.events.length, running?.current.length]);

  const send = async () => {
    const msg = text.trim();
    if (!msg || sending) return;
    setSending(true);
    try {
      await api.codingSend({ agent, text: msg, session_id: id, workspace: session?.workspace ?? "", device });
      setText("");
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setSending(false);
    }
  };

  const meta = AGENT_META[agent];
  const transcript = session?.transcript ?? [];
  // any session takes a message: the CLI reopens its own chats, and an IDE chat (not
  // resumable) gets a new chat in the same workspace with the last exchange quoted
  const canSend = !!session || !!running;
  const continuesAsNew = !!session && !session.resumable && !running;

  return (
    <Sheet
      open
      onClose={onClose}
      title={
        <span className="flex items-center gap-2.5">
          <AgentGlyph agent={agent} size={30} />
          <span className="min-w-0">
            <span className="block truncate">{session?.title || meta?.label || agent}</span>
            <span className="block truncate text-[12px] font-normal text-muted">
              {deviceLabel ? `${deviceLabel} · ` : ""}
              {session?.workspace ? basename(session.workspace) : meta?.label}
              {session?.source && session.source !== "ide" && session.source !== "cli" ? ` · ${session.source}` : ""}
            </span>
          </span>
        </span>
      }
      footer={
        <>
          {continuesAsNew && <p className="mb-1.5 px-1 text-[11.5px] leading-snug text-muted">{t("Made in the IDE: your message starts a new chat in the same workspace, with the last exchange quoted.")}</p>}
        <form
          className="flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void send();
          }}
        >
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            rows={1}
            disabled={!canSend || !!running}
            aria-label={t("Message")}
            placeholder={
              running
                ? t("{agent} is working…", { agent: meta?.label ?? agent })
                : !session
                  ? "…"
                  : continuesAsNew
                    ? t("Continue in a new chat…")
                    : t("Tell {agent}…", { agent: meta?.label ?? agent })
            }
            className={cx(inputCls, "max-h-32 min-h-[44px] resize-none py-2.5")}
          />
          {running ? (
            <button type="button" onClick={() => void api.codingStop(running.run.id, device).catch((e: Error) => toast(e.message))} aria-label={t("Stop")} className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-rose-500 text-white">
              <Square size={16} />
            </button>
          ) : (
            <button type="submit" disabled={!text.trim() || sending || !canSend} aria-label={t("Send")} className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-accent text-white disabled:opacity-40">
              {sending ? <Loader2 size={16} className="animate-spin" /> : <ArrowUp size={18} />}
            </button>
          )}
        </form>
        </>
      }
    >
      <div ref={listRef} className="space-y-2.5 py-1">
        {error && <div className="rounded-2xl bg-rose-500/12 px-3 py-2 text-[12.5px] text-rose-700 dark:text-rose-300">{error}</div>}
        {!session && !error && (
          <div className="flex justify-center py-10 text-muted">
            <Loader2 size={20} className="animate-spin" />
          </div>
        )}
        {transcript.map((m, i) => (
          <Bubble key={i} who={m.role === "user" ? "you" : "agent"} agent={agent}>
            {m.role === "user" ? <span className="whitespace-pre-wrap">{m.text}</span> : <Markdown text={m.text} />}
          </Bubble>
        ))}
        {live
          // once the agent's own store has the exchange, the transcript shows it
          .filter(
            (l) =>
              !(
                l.run.status === "done" &&
                (l.run.resumed || !l.run.asked_session_id) &&
                transcript.some((m) => m.role === "user" && m.text.trim() === l.run.text.trim())
              ),
          )
          .map((l) => (
            <LiveRun key={l.run.id} live={l} agent={agent} hideFinishedText={transcript.length > 0 && l.run.status === "done"} />
          ))}
        {session && transcript.length === 0 && live.length === 0 && <p className="py-6 text-center text-[13px] text-muted">{t("Nothing readable in this chat yet.")}</p>}
      </div>
    </Sheet>
  );
}

/** A run in a chat: what you sent, the steps, the text as it streams. */
function LiveRun({ live, agent, hideFinishedText }: { live: CodingLive; agent: string; hideFinishedText: boolean }) {
  const t = useT();
  const { run, events, current } = live;
  const tools = events.filter((e) => e.kind === "tool");
  const meta = AGENT_META[agent];
  return (
    <>
      <Bubble who="you" agent={agent} badge={t("via nanoMuse")}>
        <span className="whitespace-pre-wrap">{run.text}</span>
      </Bubble>
      {(tools.length > 0 || run.status === "running") && (
        <div className="mx-1 rounded-2xl border border-border/60 bg-surface-2/40 px-3 py-2 text-[12.5px]">
          <div className="flex items-center gap-1.5 font-medium text-fg/80">
            {run.status === "running" ? <Loader2 size={13} className="animate-spin text-accent" /> : <Wrench size={13} className="text-muted" />}
            {run.status === "running" ? t("{agent} is working…", { agent: meta?.label ?? agent }) : t("{n} steps", { n: tools.length })}
            {run.device && <span className="ml-auto flex items-center gap-1 text-muted"><MonitorSmartphone size={11} /> {run.device}</span>}
          </div>
          {tools.length > 0 && (
            <ul className="mt-1.5 max-h-28 space-y-0.5 overflow-y-auto font-mono text-[11.5px] text-muted">
              {tools.slice(-12).map((e, i) => (
                <li key={i} className="truncate">
                  {e.text}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {(current || (run.output && !hideFinishedText)) && (
        <Bubble who="agent" agent={agent}>
          <Markdown text={run.status === "running" ? (run.output ? run.output + "\n\n" : "") + current : run.output} />
          {run.status === "running" && <span className="ml-1 inline-block h-3.5 w-1 animate-pulse bg-accent align-middle" />}
        </Bubble>
      )}
      {run.status === "failed" && <div className="mx-1 rounded-2xl bg-rose-500/12 px-3 py-2 text-[12.5px] text-rose-700 dark:text-rose-300">{run.error || t("failed")}</div>}
      {run.status === "stopped" && <div className="mx-1 text-center text-[12px] text-muted">{t("stopped")}</div>}
      {!run.resumed && run.asked_session_id && run.status !== "running" && <div className="mx-1 text-center text-[12px] text-muted">{t("Continued as a new chat: the agent could not reopen the old one.")}</div>}
    </>
  );
}

function LiveRunCard({ live, onOpen }: { live: CodingLive; onOpen: () => void }) {
  const t = useT();
  const { run, events, current } = live;
  const lastTool = [...events].reverse().find((e) => e.kind === "tool");
  return (
    <button type="button" onClick={onOpen} className="flex w-full items-center gap-3 rounded-3xl border border-accent/25 bg-accent/5 px-3.5 py-3 text-left">
      <AgentGlyph agent={run.agent} size={34} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[14px] font-medium">{run.text}</span>
        <span className="mt-0.5 flex items-center gap-1.5 truncate text-[12px] text-muted">
          <Loader2 size={11} className="animate-spin text-accent" />
          <span className="truncate">{current.slice(-80) || lastTool?.text || t("starting…")}</span>
        </span>
      </span>
      {run.device && <MonitorSmartphone size={14} className="shrink-0 text-muted" />}
    </button>
  );
}

// ------------------------------------------------------------------ a new chat
export function NewChatSheet({ agent: initial, agents, device, onClose, onStarted }: { agent: string; agents: CodingAgent[]; device: string; onClose: () => void; onStarted: (run: CodingRun) => void }) {
  const { toast } = useStore();
  const t = useT();
  const workspaceId = useId();
  const textId = useId();
  const [agent, setAgent] = useState(initial);
  const [workspace, setWorkspace] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [recent, setRecent] = useState<string[]>([]);
  useEffect(() => {
    // the agent picker re-runs this; a slower answer for the earlier agent
    // must not land its workspaces under the newly picked one
    let latest = true;
    setRecent([]);
    api
      .codingSessions({ agent, device, limit: 30 })
      .then((r) => {
        if (latest) setRecent(Array.from(new Set(r.sessions.map((s) => s.workspace).filter(Boolean))).slice(0, 6));
      })
      .catch(() => {
        if (latest) setRecent([]);
      });
    return () => {
      latest = false;
    };
  }, [agent, device]);

  const start = async () => {
    if (!text.trim() || busy) return;
    setBusy(true);
    try {
      onStarted(await api.codingSend({ agent, text: text.trim(), workspace: workspace.trim(), device }));
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet
      open
      onClose={onClose}
      title={t("New chat")}
      footer={
        <button type="button" disabled={!text.trim() || busy} onClick={() => void start()} className={cx(primaryBtn, "w-full py-3")}>
          {busy ? <Loader2 size={15} className="animate-spin" /> : <ArrowUp size={15} />} {t("Send to {agent}", { agent: AGENT_META[agent]?.label ?? agent })}
        </button>
      }
    >
      <div className="space-y-4 py-1">
        <div className="grid grid-cols-3 gap-1 rounded-2xl bg-surface-2/70 p-1 text-[13px] font-medium">
          {agents.map((a) => (
            <button key={a.id} type="button" onClick={() => setAgent(a.id)} className={cx("flex items-center justify-center gap-1.5 rounded-xl px-2 py-2 transition", agent === a.id ? "bg-surface text-fg shadow-sm" : "text-muted")}>
              <AgentGlyph agent={a.id} size={18} /> {AGENT_META[a.id]?.label ?? a.name}
            </button>
          ))}
        </div>
        <div>
          <label htmlFor={workspaceId} className="text-[12px] text-muted">{t("Project folder")}</label>
          <input id={workspaceId} value={workspace} onChange={(e) => setWorkspace(e.target.value)} placeholder="/home/you/project" className={cx(inputCls, "mt-1 font-mono text-[13px]")} />
          {recent.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {recent.map((w) => (
                <button key={w} type="button" onClick={() => setWorkspace(w)} className={cx("rounded-full border px-2.5 py-1 text-[12px]", workspace === w ? "border-accent/40 bg-accent/10 text-accent" : "border-border text-muted")}>
                  {basename(w)}
                </button>
              ))}
            </div>
          )}
        </div>
        <div>
          <label htmlFor={textId} className="text-[12px] text-muted">{t("What to do")}</label>
          <textarea id={textId} value={text} onChange={(e) => setText(e.target.value)} rows={4} autoFocus placeholder={t("Add tests for the parser and run them")} className={cx(inputCls, "mt-1 resize-none")} />
        </div>
        <p className="text-[12px] text-muted">{t("The agent runs on that computer with its own permissions; nanoMuse only carries the message and brings the answer back.")}</p>
        <button type="button" onClick={onClose} className={cx(secondaryBtn, "w-full")}>
          {t("Cancel")}
        </button>
      </div>
    </Sheet>
  );
}

// ------------------------------------------------------------------ bits
function Bubble({ who, agent, badge, children }: { who: "you" | "agent"; agent: string; badge?: string; children: ReactNode }) {
  return (
    <div className={cx("flex", who === "you" ? "justify-end" : "justify-start")}>
      {who === "agent" && <AgentGlyph agent={agent} size={24} className="mr-2 mt-1 shrink-0" />}
      <div className={cx("max-w-[86%] rounded-3xl px-3.5 py-2 text-[14px] leading-relaxed", who === "you" ? "bubble-user rounded-br-lg bg-bubble-user text-bubble-user-fg" : "rounded-bl-lg bg-bubble-agent")}>
        {badge && <div className="mb-0.5 text-[10.5px] font-semibold uppercase tracking-wide opacity-60">{badge}</div>}
        <div className="md break-words">{children}</div>
      </div>
    </div>
  );
}

export function AgentGlyph({ agent, size = 28, className }: { agent: string; size?: number; className?: string }) {
  const meta = AGENT_META[agent];
  return (
    <span
      className={cx("flex shrink-0 items-center justify-center rounded-xl bg-gradient-to-br font-bold text-white shadow-sm", meta?.tone ?? "from-slate-400 to-slate-600", className)}
      style={{ width: size, height: size, fontSize: Math.round(size * 0.46) }}
      aria-hidden
    >
      {meta?.glyph ?? <Bot size={Math.round(size * 0.55)} />}
    </span>
  );
}

function StatusPill({ status }: { status: string }) {
  const t = useT();
  if (status === "running")
    return (
      <span className="flex shrink-0 items-center gap-1 rounded-full bg-emerald-500/12 px-2 py-0.5 text-[10.5px] font-semibold text-emerald-700 dark:text-emerald-300">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" /> {t("working")}
      </span>
    );
  if (status === "active") return <span className="h-2 w-2 shrink-0 rounded-full bg-accent" title={t("active")} />;
  return null;
}

function Chip({ active, onClick, icon, label }: { active: boolean; onClick: () => void; icon: ReactNode; label: string }) {
  return (
    <button type="button" onClick={onClick} className={cx("flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 text-[12.5px] font-medium transition", active ? "border-fg bg-fg text-bg" : "border-border bg-surface text-fg/75")}>
      {icon} {label}
    </button>
  );
}

function deviceName(devices: Array<{ id: string; name: string }>, id: string): string {
  return devices.find((d) => d.id === id)?.name ?? id;
}

function basename(path: string): string {
  const parts = path.replace(/[\\/]+$/, "").split(/[\\/]/);
  return parts[parts.length - 1] || path;
}
