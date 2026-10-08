import { ArrowUp, ChevronDown, FileText, Loader2, Menu, MessageSquarePlus, Monitor, MonitorSmartphone, Moon, Phone, Plus, Smartphone, Table2, Trash2, Wand2, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { api, fileUrl } from "../api";
import { AllowanceHeadsUp } from "../components/AllowanceWays";
import { cloudRetryTarget } from "../cloud-retry";
import { AvatarOptionsCard } from "../components/AvatarOptionsCard";
import { BrowserViewer } from "../components/BrowserViewer";
import { MicButton, useDictation } from "../components/Dictation";
import { ApprovalCard, ArtifactCard, BrowserCard, HandsCard, HoldCard, Notice, QuestionCard, ToolChip } from "../components/Cards";
import { IntroLines, NamingCard } from "../components/FirstConversation";
import { Markdown, splitBlocks } from "../components/Markdown";
import { MuseHeader, MuseRoundButton } from "../components/MuseHeader";
import { MoreMenu } from "../components/TabHeader";
import { stripNamingFence } from "../fences";
import { localDetail, localLabel, useLocale, useT } from "../i18n";
import { mentionSuggestions, mentionTarget } from "../mention";
import { WORKING_TTL_MS } from "../presence";
import { useStore } from "../store";
import type { AttachmentInfo, HubDevice, SkillInfo, ThreadMeta, TimelineEvent, UserEvent, WorkingPresence } from "../types";
import { cx, timeDivider, timeShort } from "../util";
import { MuseSheet } from "./MuseSheet";
import { countDay, countTask, StarNudgeOnce } from "../components/StarNudge";
import { useShowSteps } from "../steps";

export function ChatScreen() {
  const { state, send, sendViaCloud, decide, loadEvents, openFile, toast, setDrawer, setTab } = useStore();
  const t = useT();
  const { profile, status, activeThread, threads } = state;
  // undefined until the first fetch for this thread has returned — don't flash the empty state
  const loaded = state.events[activeThread];
  const events = useMemo(() => loaded ?? [], [loaded]);
  const eventsLoaded = loaded !== undefined;
  const stream = state.streams[activeThread];
  const thread = threads.find((t) => t.id === activeThread);
  const [activityOpen, setActivityOpen] = useState(false);
  // the browser card being watched (or driven) full-screen
  const [browserView, setBrowserView] = useState<string | null>(null);
  const name = profile?.name ?? "nanoMuse";
  // a chat addressed to another device: is that device still on the hub?
  const deviceOnline = thread?.device ? (state.hub?.devices.find((d) => d.id === thread.device)?.online ?? null) : null;
  // another device of the account is working on this chat (C9): the quiet line under its message
  const working = useLiveWorking(state.working[activeThread]);

  const listRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const [showJump, setShowJump] = useState(false);

  // The first conversation (contract C4), when it is bound to this chat: the runtime's state,
  // the opening lines it speaks, the chooser. `fr` is null on an older runtime.
  const fr = state.firstrun;
  const bound = !!fr && fr.phase !== "none" && fr.session_id === activeThread;
  const firstRunning = bound && fr.running;
  const locale = useLocale();
  const lang = locale === "zh-CN" ? "zh" : "en";
  const [intro, setIntro] = useState<{ lang: string; lines: string[] } | null>(null);
  useEffect(() => {
    if (!bound || intro?.lang === lang) return;
    let live = true;
    api
      .firstrun(lang)
      .then((v) => live && v.intro && setIntro({ lang, lines: v.intro }))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [bound, lang, intro?.lang]);
  const pickName = (picked: string) => {
    api
      .firstrunPick(picked)
      .then(() => send(activeThread, picked))
      .catch((e: Error) => toast(e.message || t("Could not send")));
  };
  const focusComposer = () => window.dispatchEvent(new Event("nanomuse:quick-chat"));

  // A task this browser saw through (contract C1): busy → idle, the turn started by the person
  // here (a `user` bubble, not a background notice or another device's ask) and ended with a
  // reply. The first conversation never counts: a turn that began while it was running is
  // its, whatever the phase says by the time the reply lands. The count reached is the
  // moment for a word about a star when the policy names it.
  const [taskCount, setTaskCount] = useState<number | null>(null);
  const onboarded = state.settings?.onboarded === true;
  const sawBusy = useRef(false);
  const firstRunAtStart = useRef(false);
  useEffect(() => {
    if (thread?.busy) {
      if (!sawBusy.current) firstRunAtStart.current = firstRunning;
      sawBusy.current = true;
      return;
    }
    if (!sawBusy.current) return;
    sawBusy.current = false;
    if (onboarded && !firstRunAtStart.current && !firstRunning && personStartedTurn(events)) setTaskCount(countTask());
  }, [thread?.busy, events, onboarded, firstRunning]);
  // the app was opened today: the 7th and the 30th day are moments too
  const [dayCount, setDayCount] = useState<number | null>(null);
  useEffect(() => {
    const { days, fresh } = countDay();
    if (fresh) setDayCount(days);
  }, []);

  // Pinned to the bottom while the person is there (within 120px of it); the *Latest* pill
  // only once they have scrolled more than 400px away. The pin is redone whenever the list
  // or its content changes size (a bubble finding its height, an image or a code block
  // arriving after the render, the window resized): the first version pinned once per
  // event and left the gap that opened afterwards, so the view sat short of the bottom and
  // the pill showed with nobody having scrolled.
  const pin = useCallback(() => {
    const el = listRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    setShowJump(false);
  }, []);

  const measure = useCallback(() => {
    const el = listRef.current;
    if (!el) return;
    const gap = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickToBottom.current = gap < 120;
    setShowJump(gap > 400);
  }, []);

  // a chat opens at its latest message whatever the previous chat's position was; the pill
  // of the previous chat never carries over
  const shownThread = useRef<string | null>(null);
  useLayoutEffect(() => {
    if (shownThread.current !== activeThread) {
      shownThread.current = activeThread;
      stickToBottom.current = true;
    }
    if (stickToBottom.current) pin();
  }, [events, stream?.text, activeThread, pin]);

  useEffect(() => {
    const el = listRef.current;
    const content = contentRef.current;
    if (!el || !content || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      if (stickToBottom.current) pin();
      else measure();
    });
    ro.observe(el);
    ro.observe(content);
    return () => ro.disconnect();
  }, [pin, measure]);

  const jumpToBottom = () => {
    const el = listRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  };

  const queued = state.pendingApprovals.length;
  const waitingHere = state.pendingApprovals.filter((a) => a.thread === activeThread).length;
  // The status under the name is about this chat; other chats show on the avatar badge.
  const statusLine = useMemo(() => {
    const here = !status.thread || status.thread === activeThread;
    if (waitingHere > 0 && !(here && status.state === "working")) {
      return waitingHere > 1 ? t("{n} approvals waiting for you", { n: waitingHere }) : t("1 approval waiting for you");
    }
    // Idle shows nothing under the name, as on the phone: the tag is just the name.
    if (!here) return thread?.busy ? t("On it") : undefined;
    if (status.state === "idle" && !thread?.busy) return undefined;
    if (status.detail) return status.detail;
    if (status.state === "waiting") return t("Waiting for you");
    // Between steps the line names the job, not a state of mind: "On it: book the table".
    const brief = requestBrief(events);
    return brief ? t("On it: {request}", { request: brief }) : t("On it");
  }, [status, thread, activeThread, waitingHere, events, t]);

  const pendingApprovals = events.filter((e) => e.type === "approval" && e.status === "pending").length;
  // the steps (tool chips) stay out of the chat unless asked for; everything else always shows
  const steps = useShowSteps();
  const shown = useMemo(() => (steps ? events : events.filter((e) => e.type !== "tool")), [events, steps]);
  // *Use nanoMuse Cloud this time* under a failed turn of one's own model (see cloud-retry.ts)
  const cloudRetryCtx = { signedIn: Boolean(state.hub?.account.signed_in), chatOnCloud: Boolean(state.settings?.llm.cloud), deviceChat: Boolean(thread?.device) };
  const cloudRetryFor = (i: number): (() => Promise<void>) | undefined => {
    const target = cloudRetryTarget(shown, i, cloudRetryCtx);
    return target ? () => sendViaCloud(activeThread, target.text, target.files) : undefined;
  };
  // files made in this chat: a reply that names one ("saved to `plan.md`") opens it on tap
  const files = useMemo(
    () => Array.from(new Set(events.flatMap((e) => (e.type === "artifact" ? [e.path] : [])))),
    [events],
  );

  return (
    <div className="flex h-full flex-col">
      {/* Header: Muse's — the face on its disc, the name tag with what it is doing, the round hamburger and menu */}
      <MuseHeader
        profile={profile}
        status={status}
        name={name}
        statusLine={statusLine}
        statusTone={status.state === "idle" && !thread?.busy ? "muted" : "accent"}
        spinning={((status.state === "working" && status.thread === activeThread) || !!thread?.busy) && waitingHere === 0}
        badge={queued}
        onAvatar={() => setActivityOpen(true)}
        leading={
          <MuseRoundButton onClick={() => setDrawer(true)} label={t("Chats")} dot={threads.length > 1 && activeThread !== "main"} className="wide:invisible">
            <Menu size={22} />
          </MuseRoundButton>
        }
        trailing={<MoreMenu actions={[{ label: t("Coding agents"), onClick: () => setTab("coding") }]} />}
        under={
          thread && thread.id !== "main" ? (
            thread.device ? (
              <span className="flex max-w-full items-center gap-1 rounded-full bg-accent/12 px-2.5 py-0.5 text-[11.5px] font-medium text-accent">
                {deviceOnline === false ? <span className="h-1.5 w-1.5 rounded-full bg-border" /> : <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />}
                <span className="truncate">{t("on {device}", { device: thread.device_name || thread.device })}</span>
              </span>
            ) : thread.remote_from ? (
              <span className="flex max-w-full items-center gap-1 rounded-full bg-surface-2 px-2.5 py-0.5 text-[11.5px] font-medium text-fg/80">
                <MonitorSmartphone size={11} /> <span className="truncate">{t("from {device}", { device: thread.remote_from.name })}</span>
              </span>
            ) : (
              <span className="truncate rounded-full bg-surface-2 px-2.5 py-0.5 text-[11.5px] font-medium text-fg/80">{thread.title}</span>
            )
          ) : undefined
        }
      />

      {/* Timeline */}
      <div ref={listRef} onScroll={measure} className="relative flex-1 overflow-y-auto px-3 py-3">
        <div ref={contentRef} className="space-y-2.5">
          {state.hasMore[activeThread] && events.length > 0 && (
            <div className="flex justify-center">
              <button
                type="button"
                className="text-[12.5px] text-accent px-3 py-1 rounded-full bg-surface-2"
                onClick={() => void loadEvents(activeThread, events[0]?.id)}
              >
                {t("Load earlier messages")}
              </button>
            </div>
          )}
          {/* The first conversation's opening, where the history begins: the app speaks first */}
          {bound && eventsLoaded && !state.hasMore[activeThread] && intro && <IntroLines lines={intro.lines} />}
          {eventsLoaded && events.length === 0 && !stream && !bound && (
            <EmptyChat
              name={name}
              device={thread?.device ? thread.device_name || thread.device : undefined}
              onSend={(text) => send(activeThread, text).catch((e: Error) => toast(e.message || t("Could not send")))}
            />
          )}
          {shown.map((ev, i) => (
            <EventView
              key={ev.id}
              event={ev}
              prev={shown[i - 1]}
              name={name}
              onDecide={(approved, scope) =>
                decide(ev.id, approved, scope).catch((e: Error) => toast(e.message || t("Could not send decision")))
              }
              onOpenFile={openFile}
              onOpenBrowser={setBrowserView}
              files={files}
              onCloudRetry={cloudRetryFor(i)}
            />
          ))}
          {stream && stream.text && (
            <AssistantBubble text={stream.text} streaming files={files} onOpenFile={openFile} />
          )}
          {(thread?.busy || status.state !== "idle") && !stream?.text && status.state !== "waiting" && (
            <TypingIndicator label={thread?.queued ? t("{n} queued", { n: thread.queued }) : undefined} />
          )}
          {/* the chooser for the agent's name, under the latest reply, until a pick or a typed name */}
          {bound && fr.phase === "ask_agent_name" && !thread?.busy && (
            <NamingCard chips={fr.chips} chosen={fr.chosen} onPick={pickName} onElse={focusComposer} />
          )}
          {/* A message written on another device is never this device's unfinished turn (C9):
              nothing here ever offers to continue it. While that device works, this says so. */}
          {working && !thread?.busy && <WorkingLine who={working} />}
          {!thread?.busy && status.state === "idle" && taskCount !== null && <StarNudgeOnce moment="tasks" n={taskCount} className="mx-1 my-2" />}
          {!thread?.busy && status.state === "idle" && dayCount !== null && <StarNudgeOnce moment="days_used" n={dayCount} className="mx-1 my-2" />}
        </div>
        {showJump && (
          <button
            type="button"
            onClick={jumpToBottom}
            className="sticky bottom-2 left-1/2 -translate-x-1/2 rounded-full bg-surface border border-border shadow px-3 py-1.5 text-[12.5px] flex items-center gap-1"
          >
            <ChevronDown size={14} /> {t("Latest")}{pendingApprovals ? ` · ${t("{n} approval", { n: pendingApprovals })}` : ""}
          </button>
        )}
      </div>

      <AllowanceHeadsUp />
      <Composer
        name={name}
        busy={!!thread?.busy && pendingApprovals === 0}
        waiting={events.some((e) => e.type === "question" && e.status === "pending")}
        onSend={(text, files) =>
          send(activeThread, text, files).catch((e: Error) => {
            toast(e.message || t("Could not send"));
            throw e;
          })
        }
      />

      <MuseSheet open={activityOpen} onClose={() => setActivityOpen(false)} />
      {browserView && <BrowserViewer thread={activeThread} eventId={browserView} onClose={() => setBrowserView(null)} />}
    </div>
  );
}

// ------------------------------------------------------------------ pieces
function EventView({
  event,
  prev,
  name,
  onDecide,
  onOpenFile,
  onOpenBrowser,
  files,
  onCloudRetry,
}: {
  event: TimelineEvent;
  prev?: TimelineEvent;
  name: string;
  onDecide: (approved: boolean, scope: string) => void | Promise<void>;
  onOpenFile: (path: string) => void;
  onOpenBrowser: (id: string) => void;
  files: readonly string[];
  /** a failed turn's *Use nanoMuse Cloud this time*, when it applies */
  onCloudRetry?: () => Promise<void>;
}) {
  // a small centred time, iMessage style, when the conversation pauses for a while
  const divider = needsDivider(prev, event) ? <TimeDivider ts={event.ts} /> : null;
  const body = (() => {
    switch (event.type) {
      case "user":
        return <UserBubble event={event} onOpenFile={onOpenFile} />;
      case "assistant":
        if (event.quiet) return <QuietLine text={event.text} about={event.about} ts={event.ts} />;
        return (
          <AssistantBubble
            text={event.text}
            reasoning={event.reasoning}
            continued={prev?.type === "assistant"}
            files={files}
            onOpenFile={onOpenFile}
            spoken={event.via === "call"}
            modelUsed={event.model_used}
          />
        );
      case "tool":
        return <ToolChip event={event} />;
      case "approval":
        return <ApprovalCard event={event} name={name} onDecide={onDecide} />;
      case "question":
        return <QuestionCard event={event} name={name} />;
      case "notice":
        return <Notice event={event} onCloudRetry={onCloudRetry} />;
      case "artifact":
        return <ArtifactCard event={event} onOpen={onOpenFile} />;
      case "browser":
        return <BrowserCard event={event} onOpen={onOpenBrowser} />;
      case "hands":
        return <HandsCard event={event} name={name} />;
      case "hold":
        return <HoldCard event={event} name={name} />;
      case "avatar":
        return <AvatarOptionsCard event={event} name={name} />;
      default:
        return null;
    }
  })();
  if (!body) return null;
  return (
    <>
      {divider}
      {body}
    </>
  );
}

const DIVIDER_GAP_MS = 10 * 60 * 1000;

function needsDivider(prev: TimelineEvent | undefined, event: TimelineEvent): boolean {
  if (!event.ts) return false;
  if (!prev?.ts) return true;
  return new Date(event.ts).getTime() - new Date(prev.ts).getTime() >= DIVIDER_GAP_MS;
}

function TimeDivider({ ts }: { ts?: string }) {
  const label = timeDivider(ts);
  if (!label) return null;
  return <div className="pt-2 pb-0.5 text-center text-[11.5px] font-medium text-muted">{label}</div>;
}

function UserBubble({ event, onOpenFile }: { event: UserEvent; onOpenFile: (path: string) => void }) {
  const t = useT();
  const files = event.files ?? [];
  const pictures = files.filter((f) => f.kind === "image");
  const others = files.filter((f) => f.kind !== "image");
  return (
    <div className="rise flex flex-col items-end pl-12">
      {event.via === "call" ? (
        <span className="mb-1 flex items-center gap-1 text-[11.5px] font-medium text-muted">
          <Phone size={11} /> {t("said on a call")}
        </span>
      ) : event.via ? (
        <span className="mb-1 text-[11.5px] font-medium text-muted">{t("asked from {device}", { device: event.via })}</span>
      ) : event.to_device_name || event.to_device ? (
        <span className="mb-1 flex items-center gap-1 text-[11.5px] font-medium text-accent">
          <MonitorSmartphone size={11} /> {t("to {device}", { device: event.to_device_name || event.to_device || "" })}
        </span>
      ) : (
        (event.via_device_name || event.via_device) && (
          <span className="mb-1 text-[11.5px] font-medium text-muted">{t("From {device}", { device: event.via_device_name || event.via_device || "" })}</span>
        )
      )}
      {pictures.length > 0 && (
        <div className="mb-1 flex max-w-full flex-wrap justify-end gap-1.5">
          {pictures.map((f) => (
            <button
              key={f.path}
              type="button"
              onClick={() => onOpenFile(f.path)}
              aria-label={f.name}
              className={cx("overflow-hidden rounded-2xl border border-border/60 bg-surface-2 shadow-sm active:scale-[0.98] transition", pictures.length === 1 ? "max-h-64 max-w-[240px]" : "h-28 w-28")}
            >
              <img src={fileUrl(f.path)} alt={f.name} loading="lazy" className={cx("object-cover", pictures.length === 1 ? "max-h-64 w-auto max-w-full" : "h-full w-full")} />
            </button>
          ))}
        </div>
      )}
      {others.map((f) => (
        <button
          key={f.path}
          type="button"
          onClick={() => onOpenFile(f.path)}
          className="mb-1 flex max-w-full items-center gap-2.5 rounded-2xl border border-border bg-surface px-3 py-2 text-left shadow-sm hover:bg-surface-2 active:scale-[0.98] transition"
        >
          <span className="rounded-xl bg-accent/12 p-2 text-accent">{f.kind === "data" ? <Table2 size={17} /> : <FileText size={17} />}</span>
          <span className="min-w-0">
            <span className="block truncate text-[14px] font-medium">{f.name}</span>
            <span className="block text-[11.5px] text-muted">{fileSize(f.size)}</span>
          </span>
        </button>
      ))}
      {event.text && (
        <div className="bubble-user max-w-full rounded-[20px] bg-bubble-user px-4 py-2.5 text-bubble-user-fg">
          <div className="md text-[15px] leading-[1.45] whitespace-pre-wrap break-words">{event.text}</div>
        </div>
      )}
    </div>
  );
}

function fileSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/** A file picked in the composer: uploading, uploaded, or failed. */
interface Pending {
  key: string;
  file: File;
  preview: string | null;
  info: AttachmentInfo | null;
  error: string | null;
}

function chipKind(name: string): "data" | "other" {
  const ext = name.toLowerCase().split(".").pop() ?? "";
  return ["csv", "tsv", "json", "xlsx", "xls"].includes(ext) ? "data" : "other";
}

const ACCEPT = "image/*,.pdf,.txt,.md,.csv,.tsv,.json,.log,.html,.xml,.yaml,.yml,.toml,.ics,.vcf,.xlsx,.xls,.docx";

function AssistantBubble({
  text,
  reasoning,
  streaming,
  continued,
  files,
  onOpenFile,
  spoken,
  modelUsed,
}: {
  text: string;
  reasoning?: string;
  streaming?: boolean;
  continued?: boolean;
  files?: readonly string[];
  /** said aloud on a call rather than written */
  spoken?: boolean;
  /** *Use nanoMuse Cloud this time*: the account's model this reply came from */
  modelUsed?: string;
  onOpenFile?: (path: string) => void;
}) {
  const [showReasoning, setShowReasoning] = useState(false);
  const t = useT();
  // the model's block for the app (the first conversation's names) is never shown — not even
  // the half of it a stream has delivered so far
  const blocks = useMemo(() => splitBlocks(stripNamingFence(text, !!streaming)), [text, streaming]);
  if (blocks.length === 0 && !streaming && !reasoning) return null;
  return (
    <div className={cx("rise flex items-end gap-2 pr-10", continued && "-mt-1")}>
      <div className="min-w-0 max-w-full">
        {reasoning && (
          <button type="button" className="mb-1 ml-1 text-[12px] text-muted" onClick={() => setShowReasoning((s) => !s)}>
            {showReasoning ? t("Hide thinking") : t("Show thinking")}
          </button>
        )}
        {reasoning && showReasoning && (
          <div className="mb-1.5 rounded-2xl bg-surface-2/70 px-3 py-2 text-[13px] text-muted whitespace-pre-wrap break-words">
            {reasoning}
          </div>
        )}
        {/* Muse's grey bubbles: one per block of the reply; code and tables carry their own frame */}
        {blocks.map((b, i) =>
          b.bare ? (
            <div key={i} className="my-1 max-w-full">
              <Markdown text={b.text} files={files} onOpenFile={onOpenFile} />
            </div>
          ) : (
            <div key={i} className={cx("my-1 max-w-[340px] rounded-[20px] bg-surface-2 px-3.5 py-2.5 wide:max-w-[600px]", spoken && "border border-accent/15")}>
              {spoken && i === 0 && (
                <div className="mb-0.5 flex items-center gap-1 text-[11px] font-medium text-accent/80">
                  <Phone size={10} /> {t("said on a call")}
                </div>
              )}
              <Markdown text={b.text} files={files} onOpenFile={onOpenFile} />
              {streaming && i === blocks.length - 1 && <span className="inline-block w-1.5 h-4 ml-0.5 align-middle bg-accent/70 animate-pulse rounded-sm" />}
            </div>
          ),
        )}
        {blocks.length === 0 && streaming && (
          <div className="my-1 rounded-[20px] bg-surface-2 px-3.5 py-2.5">
            <span className="inline-block w-1.5 h-4 align-middle bg-accent/70 animate-pulse rounded-sm" />
          </div>
        )}
        {modelUsed && !streaming && <div className="ml-1 text-[11px] text-muted">{t("Answered by nanoMuse Cloud this time ({model})", { model: modelUsed })}</div>}
      </div>
    </div>
  );
}

/** A background pass that found nothing worth interrupting you for: one muted line, not a bubble. */
function QuietLine({ text, about, ts }: { text: string; about?: string; ts?: string }) {
  const [open, setOpen] = useState(false);
  const t = useT();
  const label = about ? localLabel(about.replace(/^Working on your goal: /, "")) : t("background check");
  return (
    <div className="rise flex justify-center px-6">
      <button type="button" onClick={() => setOpen((o) => !o)} className="max-w-full rounded-2xl px-3 py-1.5 text-[12px] text-muted text-center leading-snug">
        <span className="inline-flex items-center gap-1.5">
          <Moon size={12} /> {t("Checked on {label}: nothing new", { label })}{ts ? ` · ${timeShort(ts)}` : ""}
        </span>
        {open && <span className="block mt-1 text-left whitespace-pre-wrap text-[12.5px]">{text}</span>}
      </button>
    </div>
  );
}

function TypingIndicator({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2">
      <div className="rounded-[20px] rounded-bl-md bg-surface-2 px-3.5 py-2.5 flex items-center gap-1">
        <span className="typing-dot h-2 w-2 rounded-full bg-muted" />
        <span className="typing-dot h-2 w-2 rounded-full bg-muted" />
        <span className="typing-dot h-2 w-2 rounded-full bg-muted" />
      </div>
      {label && <span className="text-[12px] text-muted">{label}</span>}
    </div>
  );
}

/**
 * The presence line for this chat while it is worth showing (C9): the entry as the store
 * holds it, or null once it is ten minutes old. Re-renders at the moment it expires, so the
 * line goes on its own when the other device never said it was done.
 */
function useLiveWorking(who: WorkingPresence | undefined): WorkingPresence | null {
  const expiresAt = who ? who.at * 1000 + WORKING_TTL_MS : 0;
  // the moment this entry went stale (0 while it is live); set by the timer below
  const [expired, setExpired] = useState(0);
  useEffect(() => {
    if (!expiresAt) return;
    const left = expiresAt - Date.now();
    if (left <= 0) {
      setExpired(expiresAt);
      return;
    }
    const timer = window.setTimeout(() => setExpired(expiresAt), left + 50);
    return () => window.clearTimeout(timer);
  }, [expiresAt]);
  if (!who || expired === expiresAt) return null;
  return who;
}

/** "Pixel 8 is working…" — quiet, under the message the other device is answering. */
function WorkingLine({ who }: { who: WorkingPresence }) {
  const t = useT();
  return (
    <div className="flex items-center gap-1.5 px-1 text-[12px] text-muted">
      <Loader2 size={12} className="animate-spin" />
      <span>{t("{device} is working…", { device: who.device_name || who.device })}</span>
    </div>
  );
}

function EmptyChat({ name, device, onSend }: { name: string; device?: string; onSend: (text: string) => void }) {
  const t = useT();
  const starters = device
    ? [t("What is on your screen right now?"), t("Which folder are you in, and what is in it?"), t("Check for updates and tell me what needs a restart")]
    : [
        t("What can you do for me?"),
        t("Plan my week: ask me what's on my plate"),
        t("Research and compare two options for me"),
        t("Set up a long-term goal and track it"),
      ];
  // The face is already in the header above; here the agent speaks, as it does on the phone.
  return (
    <div className="flex flex-col items-center text-center px-6 pt-10 pb-6 gap-3">
      <div className="text-[20px] font-semibold">{device ? t("This chat goes to {device}.", { device }) : t("Hi, I'm {name}.", { name })}</div>
      <p className="text-muted text-[14.5px] leading-snug max-w-sm">
        {device
          ? t("Whatever you ask here, the {name} on {device} does where it is: its shell, its files, its screen. Every step shows up here, and anything that needs an approval asks you here.", { name, device })
          : t("I don't just answer; I get things done: research, plans, files, code, email, long-running goals. Everything I do shows up here, and anything hard to undo waits for your approval.")}
      </p>
      <div className="mt-2 flex flex-wrap justify-center gap-2">
        {starters.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onSend(s)}
            className="rounded-full bg-surface-2 px-3.5 py-1.5 text-[13.5px] hover:bg-border/60"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

function Composer({
  name,
  busy,
  waiting,
  onSend,
}: {
  name: string;
  busy: boolean;
  waiting: boolean;
  onSend: (text: string, files: string[]) => Promise<void>;
}) {
  const { state, draft, draftFiles, toast } = useStore();
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  // voice input: the words recognised so far replace what dictation put in the box, after
  // whatever was typed before the mic was tapped
  const typedBefore = useRef("");
  const dictation = useDictation(
    useCallback((final: string, interim: string) => {
      const lead = typedBefore.current;
      const sep = lead && !/\s$/.test(lead) ? " " : "";
      setText(lead + sep + final + interim);
    }, []),
    useCallback((message: string) => toast(message), [toast]),
  );
  const toggleDictation = () => {
    if (!dictation.listening) typedBefore.current = text;
    dictation.toggle();
  };
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [pending, setPending] = useState<Pending[]>([]);

  // files shared from another app on the phone: uploaded already, they only need chips
  useEffect(() => {
    if (!state.draftFiles) return;
    const items: Pending[] = state.draftFiles.map((info) => ({
      key: `shared-${info.path}`,
      file: new File([], info.name),
      preview: info.kind === "image" ? fileUrl(info.path) : null,
      info,
      error: null,
    }));
    setPending((cur) => [...cur.filter((p) => !items.some((i) => i.key === p.key)), ...items].slice(0, 10));
    draftFiles(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.draftFiles]);
  const ref = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const t = useT();

  // previews are object URLs; let them go when the chip goes
  useEffect(() => () => pending.forEach((p) => p.preview?.startsWith("blob:") && URL.revokeObjectURL(p.preview)), [pending]);

  // the desktop's quick-chat shortcut: the window is up, the cursor goes here
  useEffect(() => {
    const focus = () => ref.current?.focus();
    window.addEventListener("nanomuse:quick-chat", focus);
    return () => window.removeEventListener("nanomuse:quick-chat", focus);
  }, []);

  const addFiles = (list: FileList | File[]) => {
    const files = Array.from(list).slice(0, Math.max(0, 10 - pending.length));
    if (files.length === 0) return;
    const items: Pending[] = files.map((file) => ({
      key: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2, 7)}`,
      file,
      preview: file.type.startsWith("image/") ? URL.createObjectURL(file) : null,
      info: null,
      error: null,
    }));
    setPending((cur) => [...cur, ...items]);
    for (const item of items) {
      api.upload(item.file)
        .then((info) => setPending((cur) => cur.map((p) => (p.key === item.key ? { ...p, info } : p))))
        .catch((e: Error) => {
          const why = e.message ? localDetail(e.message) : t("Upload failed");
          setPending((cur) => cur.map((p) => (p.key === item.key ? { ...p, error: why } : p)));
          toast(why);
        });
    }
  };
  const remove = (key: string) => setPending((cur) => cur.filter((p) => p.key !== key));
  const uploading = pending.some((p) => !p.info && !p.error);
  const attached = pending.flatMap((p) => (p.info ? [p.info.path] : []));

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [text]);

  // text handed over from another screen (a skill's "Use" button)
  useEffect(() => {
    if (state.draft === null) return;
    setText(state.draft);
    draft(null);
    const el = ref.current;
    if (el) {
      el.focus();
      el.setSelectionRange(el.value.length, el.value.length);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.draft]);

  // "/" at the start of the message offers the skills; the list is small and cached
  const skillsOn = state.settings?.skills?.enabled !== false;
  useEffect(() => {
    if (!skillsOn) return;
    api.skills()
      .then((d) => setSkills(d.skills.filter((sk) => sk.enabled)))
      .catch(() => setSkills([]));
  }, [skillsOn, state.skillsVersion]);
  const slash = /^\/([a-z0-9-]*)$/i.exec(text);
  const matches = slash ? skills.filter((sk) => sk.name.startsWith(slash[1].toLowerCase())).slice(0, 6) : [];
  const pick = (sk: SkillInfo) => {
    setText(`/${sk.name} `);
    ref.current?.focus();
  };
  // "@" at the start names another device of the account: the turn runs there (contract C7 rule 8)
  const hubDevices = state.hub?.devices ?? [];
  const mentions = mentionSuggestions(text, hubDevices);
  const target = mentions.length === 0 ? mentionTarget(text, hubDevices) : null;
  const pickDevice = (d: HubDevice) => {
    setText(`@${d.name} `);
    ref.current?.focus();
  };

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const trimmed = text.trim();
    if ((!trimmed && attached.length === 0) || uploading || sending) return;
    if (dictation.listening) dictation.stop();
    // the draft leaves the box at once (it feels sent) and comes back if sending failed
    const files = pending;
    setSending(true);
    setText("");
    setPending([]);
    ref.current?.focus();
    onSend(trimmed, attached)
      .catch(() => {
        setText((cur) => cur || trimmed);
        setPending((cur) => (cur.length ? cur : files));
      })
      .finally(() => setSending(false));
  };

  return (
    <form onSubmit={submit} className="shrink-0 bg-bg px-3 pt-1.5 pb-1">
      {busy && !waiting && (
        <div className="px-2 pb-1 text-[12px] text-muted">{t("{name} is working; anything you send now is picked up right away.", { name })}</div>
      )}
      {matches.length > 0 && (
        <ul className="mb-2 max-h-72 overflow-y-auto rounded-3xl border border-border/70 bg-surface shadow-lg divide-y divide-border/70" role="listbox" aria-label={t("Skills")}>
          {matches.map((sk) => (
            <li key={sk.name}>
              <button type="button" onClick={() => pick(sk)} className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-surface-2/70 active:bg-surface-2">
                <Wand2 size={16} className="shrink-0 text-accent" />
                <span className="min-w-0 flex-1">
                  <span className="block text-[14px] font-medium">/{sk.name}</span>
                  <span className="block truncate text-[12.5px] text-muted">{sk.description}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {mentions.length > 0 && (
        <ul className="mb-2 max-h-72 overflow-y-auto rounded-3xl border border-border/70 bg-surface shadow-lg divide-y divide-border/70" role="listbox" aria-label={t("Devices")}>
          {mentions.map((d) => (
            <li key={d.id}>
              <button type="button" onClick={() => pickDevice(d)} className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-surface-2/70 active:bg-surface-2">
                <span className="shrink-0 text-accent">{d.kind === "computer" ? <Monitor size={16} /> : <Smartphone size={16} />}</span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[14px] font-medium">@{d.name}</span>
                  <span className="block truncate text-[12.5px] text-muted">{d.online ? t("Runs this there and reports back") : t("Offline")}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {target && (
        <div className="flex items-center gap-1.5 px-2 pb-1 text-[12px] text-muted">
          <MonitorSmartphone size={12} /> {t("This goes to {device}.", { device: target.name })}
        </div>
      )}
      {pending.length > 0 && (
        <div className="mb-1 flex gap-2.5 overflow-x-auto px-1 pt-2.5 pb-1 pr-3" role="list" aria-label={t("Attachments")}>
          {pending.map((p) => (
            <div key={p.key} role="listitem" className={cx("relative shrink-0 rounded-2xl border bg-surface-2", p.error ? "border-danger/60" : "border-border/70")}>
              {p.preview ? (
                <img src={p.preview} alt={p.file.name} className="h-16 w-16 rounded-2xl object-cover" />
              ) : (
                <div className="flex h-16 w-40 items-center gap-2 px-2.5">
                  <span className="rounded-xl bg-accent/12 p-1.5 text-accent">{chipKind(p.file.name) === "data" ? <Table2 size={16} /> : <FileText size={16} />}</span>
                  <span className="min-w-0">
                    <span className="block truncate text-[12.5px] font-medium">{p.file.name}</span>
                    <span className="block text-[11px] text-muted">{p.error ? t("Upload failed") : fileSize(p.info?.size ?? p.file.size)}</span>
                  </span>
                </div>
              )}
              {!p.info && !p.error && (
                <div className="absolute inset-0 flex items-center justify-center rounded-2xl bg-bg/50">
                  <Loader2 size={18} className="animate-spin text-accent" />
                </div>
              )}
              <button
                type="button"
                onClick={() => remove(p.key)}
                aria-label={t("Remove")}
                className="absolute -right-1.5 -top-1.5 flex h-6 w-6 items-center justify-center rounded-full border border-border bg-surface text-muted shadow-sm"
              >
                <X size={13} />
              </button>
            </div>
          ))}
        </div>
      )}
      <div className="flex items-end gap-2 rounded-[26px] border border-border bg-surface px-1.5 py-1.5 shadow-[0_2px_12px_-6px_rgba(0,0,0,0.12)] focus-within:border-fg/20">
        <input
          ref={fileRef}
          type="file"
          multiple
          accept={ACCEPT}
          className="hidden"
          onChange={(e) => {
            if (e.target.files) addFiles(e.target.files);
            e.target.value = "";
          }}
        />
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          aria-label={t("Attach a file")}
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-fg/70 transition hover:bg-surface-2 active:scale-95"
        >
          <Plus size={22} />
        </button>
        <textarea
          ref={ref}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onPaste={(e) => {
            const files = Array.from(e.clipboardData?.files ?? []);
            if (files.length > 0) {
              e.preventDefault();
              addFiles(files);
            }
          }}
          onKeyDown={(e) => {
            if (e.key === "Tab" && matches.length > 0 && matches[0]) {
              e.preventDefault();
              pick(matches[0]);
              return;
            }
            if (e.key === "Tab" && mentions.length > 0 && mentions[0]) {
              e.preventDefault();
              pickDevice(mentions[0]);
              return;
            }
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          rows={1}
          placeholder={waiting ? t("Answer {name}…", { name }) : pending.length > 0 ? t("Say what to do with it…") : t("Message")}
          className="flex-1 resize-none bg-transparent px-1 py-2 text-[15px] leading-[1.4] outline-none placeholder:text-muted"
        />
        {dictation.supported && <MicButton listening={dictation.listening} onClick={toggleDictation} />}
        <button
          type="submit"
          disabled={(!text.trim() && attached.length === 0) || uploading}
          aria-label={t("Send")}
          className={cx(
            "flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition active:scale-95",
            text.trim() || attached.length > 0 ? "bg-accent text-accent-fg" : "bg-surface-2 text-muted",
            "disabled:opacity-60",
          )}
        >
          <ArrowUp size={19} strokeWidth={2.5} />
        </button>
      </div>
    </form>
  );
}

/** The list of chats with the devices a chat can be addressed to and the new-chat row; the sheet on the phone, the sidebar on a wide screen. */
export function ThreadList({
  threads,
  active,
  onPick,
  onCleared,
  compact = false,
  grouped = false,
}: {
  threads: ThreadMeta[];
  active: string;
  onPick: (id: string) => void;
  onCleared?: () => void;
  compact?: boolean;
  /** the main chat on its own, then the side chats under their own heading with a + (the desktop's chats column) */
  grouped?: boolean;
}) {
  const { state, toast, dispatch } = useStore();
  const t = useT();
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const newInput = useRef<HTMLInputElement>(null);
  // devices of yours on the hub that a chat can be addressed to
  const devices: HubDevice[] = (state.hub?.devices ?? []).filter((d) => !d.this && d.kind !== "web" && d.online);
  const kindOf = (id: string) => state.hub?.devices.find((d) => d.id === id)?.kind ?? "phone";

  const ask = async (d: HubDevice) => {
    try {
      const r = await api.askDevice(d.id);
      dispatch({ type: "ws", msg: { kind: "thread", thread: r.thread } });
      onPick(r.thread.id);
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const create = async () => {
    setCreating(true);
    try {
      const created = await api.createThread(title.trim() || t("Side chat"));
      dispatch({ type: "ws", msg: { kind: "thread", thread: created } });
      setTitle("");
      onPick(created.id);
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setCreating(false);
    }
  };

  const remove = async (id: string) => {
    if (!window.confirm(t("Delete this side chat and its history?"))) return;
    try {
      await api.deleteThread(id);
      dispatch({ type: "ws", msg: { kind: "thread_deleted", thread: id } });
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const clear = async (id: string) => {
    if (!window.confirm(t("Clear this conversation? Memory and goals are kept."))) return;
    try {
      await api.clearThread(id);
      dispatch({ type: "ws", msg: { kind: "thread_cleared", thread: id } });
      onCleared?.();
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const row = (th: ThreadMeta) => (
          <li key={th.id} className={cx("group flex items-center gap-2 px-3", compact ? "py-2 rounded-xl hover:bg-surface-2/60" : "py-2.5", th.id === active && "bg-surface-2/60")}>
            <button type="button" onClick={() => onPick(th.id)} className="flex-1 text-left min-w-0">
              <div className={cx("font-medium truncate flex items-center gap-2", compact ? "text-[13.5px]" : "text-[15px]")}>
                {th.device ? (
                  <span className="text-accent">{kindOf(th.device) === "computer" ? <Monitor size={14} /> : <Smartphone size={14} />}</span>
                ) : th.remote_from ? (
                  <MonitorSmartphone size={14} className="text-muted" />
                ) : null}
                <span className="truncate">{th.id === "main" ? t(th.title) : th.title}</span>
                {th.busy && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400 animate-pulse" />}
              </div>
              <div className={cx("text-muted", compact ? "text-[11.5px]" : "text-[12px]")}>
                {t("{n} events", { n: th.events })}{th.queued ? ` · ${t("{n} queued", { n: th.queued })}` : ""} · {timeShort(th.updated_at)}
              </div>
            </button>
            <button type="button" aria-label={t("Clear")} onClick={() => void clear(th.id)} className={cx("p-2 text-muted hover:text-fg", compact && "opacity-0 group-hover:opacity-100 focus:opacity-100")}>
              <X size={16} />
            </button>
            {th.id !== "main" && (
              <button
                type="button"
                aria-label={t("Delete")}
                onClick={() => void remove(th.id)}
                className={cx("p-2 text-muted hover:text-rose-500", compact && "opacity-0 group-hover:opacity-100 focus:opacity-100")}
              >
                <Trash2 size={16} />
              </button>
            )}
          </li>
  );
  const listCls = cx("divide-y divide-border overflow-hidden", compact ? "rounded-xl" : "rounded-2xl border border-border");
  const heading = "px-3 pb-1 pt-3 text-[11.5px] font-semibold uppercase tracking-wide text-muted";

  return (
    <div>
      {grouped ? (
        <>
          <div className={heading}>{t("Main chat")}</div>
          <ul className={listCls}>{threads.filter((th) => th.id === "main").map(row)}</ul>
          <div className={cx(heading, "flex items-center justify-between pr-1")}>
            <span>{t("Side chats")}</span>
            <button
              type="button"
              aria-label={t("New side chat")}
              onClick={() => newInput.current?.focus()}
              className="flex h-6 w-6 items-center justify-center rounded-full text-muted hover:bg-surface-2 hover:text-fg"
            >
              <Plus size={15} />
            </button>
          </div>
          <ul className={listCls}>{threads.filter((th) => th.id !== "main").map(row)}</ul>
          {threads.every((th) => th.id === "main") && <p className="px-3 py-2 text-[12px] text-muted">{t("A side chat keeps one topic apart from the rest.")}</p>}
        </>
      ) : (
        <ul className={listCls}>{threads.map(row)}</ul>
      )}
      {devices.length > 0 && (
        <div className="mt-4">
          <div className="mb-1.5 text-[12px] font-medium text-muted">{t("Ask one of your devices")}</div>
          <div className="flex flex-wrap gap-2">
            {devices.map((d) => (
              <button
                key={d.id}
                type="button"
                onClick={() => void ask(d)}
                className="flex items-center gap-1.5 rounded-full border border-border bg-surface px-3 py-1.5 text-[13px] font-medium hover:bg-surface-2"
              >
                {d.kind === "phone" ? <Smartphone size={14} className="text-accent" /> : <Monitor size={14} className="text-accent" />}
                {d.name}
              </button>
            ))}
          </div>
        </div>
      )}
      <div className={cx("flex gap-2", compact ? "mt-3" : "mt-4")}>
        <input
          ref={newInput}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !creating) void create();
          }}
          placeholder={compact ? t("New side chat") : t("New side chat, e.g. “Trip to Kyoto”")}
          className={cx("min-w-0 flex-1 bg-surface-2 outline-none focus:ring-2 focus:ring-accent/40", compact ? "rounded-xl px-3 py-2 text-[13px]" : "rounded-2xl px-3.5 py-2.5 text-[14px]")}
        />
        <button
          type="button"
          disabled={creating}
          onClick={() => void create()}
          aria-label={t("New")}
          className={cx("flex items-center gap-1.5 bg-accent text-accent-fg font-medium disabled:opacity-50", compact ? "rounded-xl px-2.5" : "rounded-2xl px-3.5 py-2.5")}
        >
          <MessageSquarePlus size={18} /> {!compact && t("New")}
        </button>
      </div>
    </div>
  );
}

/** The person's request, briefly, for "On it: …": its first line, folded, cut at a word. */
function requestBrief(events: TimelineEvent[]): string {
  const last = [...events].reverse().find((e) => e.type === "user");
  const text = last?.type === "user" ? last.text : "";
  const line = (text || "").split(/\r?\n/).map((l) => l.trim()).find((l) => l.length > 0) ?? "";
  const folded = line.replace(/\s+/g, " ");
  if (folded.length <= 36) return folded;
  const cut = folded.slice(0, 36);
  const at = cut.lastIndexOf(" ");
  return (at > 16 ? cut.slice(0, at) : cut).trimEnd() + "…";
}

/**
 * The turn that just ended was the person's: walking back from the end, a reply with words,
 * then the bubble that started it — `user` (typed, dictated, an idea tapped) counts; a
 * background notice (a routine, the feed, a goal check-in) or an ask from another device
 * does not.
 */
export function personStartedTurn(events: TimelineEvent[]): boolean {
  let replied = false;
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.type === "assistant") {
      if (!e.text || e.quiet) return false;
      replied = true;
      continue;
    }
    if (e.type === "user") return replied && !e.via;
    if (e.type === "notice") return false;
  }
  return false;
}
