import {
  BarChart3,
  BatteryFull,
  Bell,
  Box,
  Brain,
  Check,
  ChevronRight,
  Clapperboard,
  Cloud,
  Code2,
  DatabaseZap,
  Hand,
  Info,
  LogOut,
  MessageSquare,
  MessageSquareWarning,
  Monitor,
  Moon,
  Palette,
  Plug,
  Puzzle,
  Search,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Smile,
  Sparkles,
  TerminalSquare,
  Zap,
} from "lucide-react";
import { Fragment, useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { androidApp, keepRunningStatus, type KeepRunningStatus } from "../android";
import { api, setToken } from "../api";
import { DRAGON } from "../avatars";
import { desktopBridge, isDesktopApp } from "../desktop";
import { setDeveloperTools, useDeveloperTools } from "../devtools";
import { setShowSteps, useShowSteps } from "../steps";
import { clearMarks, filterPages, hitLabel, markMatches, queryWords } from "../settings-search";
import { openOwnKeySetup } from "../components/AllowanceWays";
import { AVATAR_COLORS } from "../components/AvatarPicker";
import { IdentityForm, identityBody, identityOf, type Identity } from "../components/IdentityForm";
import { PageBar } from "../components/BackBar";
import { CommunityNotice } from "../components/CommunityNotice";
import { DataControls, PRIVACY_URL } from "../components/DataControls";
import { getLocale, LOCALES, setLocaleSetting, useLocaleSetting, useT } from "../i18n";
import { has, regionOf, unavailableLine, useProviders } from "../providers";
import { isMainland, ownKeyWay } from "../region";
import { setThemeSetting, useThemeSetting } from "../theme";
import { disablePush, enablePush, pushState, type PushState } from "../push";
import { useStore } from "../store";
import type { Proactivity, PushInfo, UpdateView } from "../types";
import { MuseCaption, MuseCard, MuseDivider, MuseRow } from "../components/MuseList";
import { useWide } from "../useWide";
import { cx, relativeTime } from "../util";
import { Toggle } from "../components/Form";

const settingsInput = "w-full rounded-2xl bg-surface-2 px-3.5 py-2.5 outline-none focus:ring-2 focus:ring-accent/40";

const MODES: Array<{ id: "ask" | "strict" | "auto"; title: string; text: string; icon: ReactNode }> = [
  {
    id: "ask",
    title: "Balanced",
    text: "Browse, read and write files freely; stop for anything hard to undo: email, purchases, shell commands.",
    icon: <ShieldCheck size={18} />,
  },
  {
    id: "strict",
    title: "Cautious",
    text: "Also ask before moderate actions like fetching web pages or writing files.",
    icon: <Shield size={18} />,
  },
  {
    id: "auto",
    title: "Hands-off",
    text: "Ordinary actions run automatically. Deny rules still apply; warnings and private data sent to unapproved destinations still need permission.",
    icon: <ShieldAlert size={18} />,
  },
];

export function SettingsScreen() {
  const { state, refreshSettings, setTab, toast } = useStore();
  const s = state.settings;
  const [identity, setIdentity] = useState<Identity>(() => identityOf(state.profile, DRAGON, AVATAR_COLORS[0]));
  const [saving, setSaving] = useState(false);
  const t = useT();
  const localeSetting = useLocaleSetting();
  const themeSetting = useThemeSetting();
  const [release, setRelease] = useState<UpdateView | null>(null);
  const [checking, setChecking] = useState(false);
  // the four selects and the label beside each: one id per pair, so the label names the control
  const ids = useId();
  const intervalId = `${ids}-interval`;
  const themeId = `${ids}-theme`;
  const appLangId = `${ids}-app-language`;
  const replyLangId = `${ids}-reply-language`;

  useEffect(() => {
    if (!s) void refreshSettings();
  }, [s, refreshSettings]);

  // the runtime asks nanomuse.cn/dl (then GitHub) at most once a day; "Check now" asks again
  const checkRelease = useCallback(async (refresh = false) => {
    setChecking(true);
    try {
      setRelease(await api.update(refresh));
    } catch {
      setRelease(null);
    } finally {
      setChecking(false);
    }
  }, []);
  useEffect(() => {
    void checkRelease();
  }, [checkRelease]);

  useEffect(() => {
    if (state.profile) setIdentity(identityOf(state.profile, "", AVATAR_COLORS[0]));
  }, [state.profile]);

  const update = async (body: Record<string, unknown>, msg?: string) => {
    setSaving(true);
    try {
      await api.updateSettings(body);
      await refreshSettings();
      if (msg) toast(msg);
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const saved = identityOf(state.profile, "", AVATAR_COLORS[0]);
  const dirty = !!state.profile && (Object.keys(identity) as (keyof Identity)[]).some((k) => identity[k] !== saved[k]);
  const name = state.profile?.name ?? "nanoMuse";
  const developer = useDeveloperTools();
  const steps = useShowSteps();
  // One page on a wide window (the sections down the left, the way Muse's desktop settings
  // read); on the phone the list of rows the Android app draws, each opening its own page.
  const wide = useWide() && !state.lite;
  const [page, setPage] = useState<SectionId | null>(null);
  // the settings search: the sections by their title, and the words in the sections
  // themselves, the rule the desktop app's settings search states (../settings-search)
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<Array<{ element: HTMLElement; label: string }>>([]);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const navRef = useRef<HTMLElement | null>(null);
  const sections: Array<{ id: SectionId; title: string }> = [
    { id: "who", title: name },
    { id: "sentinel", title: t("Safety · Sentinel") },
    { id: "proactivity", title: t("Proactivity") },
    { id: "notifications", title: t("Notifications") },
    ...(keepRunningStatus() ? [{ id: "keep-running" as const, title: t("Keep it running") }] : []),
    { id: "model", title: t("Model") },
    { id: "appearance", title: t("Appearance") },
    ...(isDesktopApp() ? [{ id: "desktop" as const, title: t("Desktop app") }] : []),
    { id: "data", title: t("Data controls") },
    { id: "developer", title: t("Developer") },
    { id: "about", title: t("About") },
  ];
  const show = (id: SectionId) => wide || page === id;
  const searching = queryWords(query).length > 0;
  const pageHits = filterPages(
    sections.map((sec) => ({ id: sec.id, label: sec.title })),
    query,
  );
  const matching = new Set(pageHits.map((p) => p.id));

  // The query on the sections in view: the words that match are marked where they
  // stand and listed under the field, so a setting is found by its own words. The
  // first hit is scrolled to when the query changes; a settings save re-marks
  // without moving the page.
  const asked = useRef("");
  useEffect(() => {
    const root = bodyRef.current;
    if (root === null) {
      setHits([]);
      return;
    }
    const marked = markMatches(root, query);
    // a row's title and the line under it are one hit, not two
    const grouped = new Map<HTMLElement, { element: HTMLElement; label: string }>();
    for (const element of marked) {
      const key = element.parentElement ?? element;
      if (!grouped.has(key)) grouped.set(key, { element, label: hitLabel(element) });
    }
    setHits([...grouped.values()]);
    const queryChanged = asked.current !== query;
    if (queryChanged && queryWords(query).length > 0) {
      marked[0]?.scrollIntoView({ block: "center" });
      // the hits are listed at the top of the nav, so the nav goes back to the top
      // when the query starts, or they would be out of sight
      if (asked.current.trim() === "") navRef.current?.scrollTo({ top: 0 });
    }
    asked.current = query;
    return () => {
      clearMarks(root);
    };
  }, [query, s, wide]);

  const onSearchKey = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") {
      // the field clears first; an empty field leaves Escape to the page
      if (query.trim() === "") return;
      event.preventDefault();
      setQuery("");
      return;
    }
    if (event.key !== "Enter") return;
    event.preventDefault();
    const firstPage = pageHits[0];
    if (firstPage !== undefined) {
      document.getElementById(firstPage.id)?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    hits[0]?.element.scrollIntoView({ block: "center" });
  };

  // `#developer` (the sidebar's menu), `#who` (the agent page's Edit) and the other section
  // ids land on that section — once the settings are in, so the sections above it have
  // their final height; on the phone they open that page.
  const [wanted, setWanted] = useState<SectionId | null>(() => {
    const id = window.location.hash.slice(1);
    return SECTION_IDS.includes(id as SectionId) ? (id as SectionId) : null;
  });
  useEffect(() => {
    if (!wanted || !s) return;
    setWanted(null);
    history.replaceState(null, "", window.location.pathname + window.location.search);
    if (!wide) {
      setPage(wanted);
      return;
    }
    requestAnimationFrame(() => document.getElementById(wanted)?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }, [wanted, s, wide]);

  if (!wide && page === null) {
    return <SettingsHome release={release} onOpen={setPage} sections={sections} query={query} onQuery={setQuery} />;
  }
  const current = sections.find((x) => x.id === page);

  return (
    <div className="flex h-full flex-col">
      {wide ? (
        <PageBar title={t("Settings")} description={t("Its name and look, how careful it is, how often it speaks up.")} />
      ) : (
        <PageBar title={current?.title ?? t("Settings")} onBack={() => setPage(null)} backLabel={t("Settings")} />
      )}

      <div className="flex min-h-0 flex-1">
        {/* on a wide window, the sections down the left — the shape of Muse's settings */}
        {wide && (
          <nav ref={navRef} className="flex max-h-full w-[188px] shrink-0 flex-col gap-0.5 self-start overflow-y-auto pl-4 pr-2 pt-1" aria-label={t("Settings")}>
            {/* the search: the sections by their title, and the words in the sections themselves */}
            <div className="px-1 pb-1">
              <div className="flex items-center gap-2 rounded-xl bg-surface-2 px-2.5 py-1.5">
                <Search size={14} className="shrink-0 text-muted" />
                <input
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.currentTarget.value)}
                  onKeyDown={onSearchKey}
                  placeholder={t("Search settings")}
                  aria-label={t("Search settings")}
                  className="w-full bg-transparent text-[13px] outline-none placeholder:text-muted"
                />
              </div>
            </div>
            {searching && (
              <div className="pb-1">
                {hits.length > 0 && (
                  <>
                    <div className="px-3 pb-0.5 pt-1 text-[11px] font-semibold uppercase tracking-wide text-muted">{t("On this page")}</div>
                    {hits.map((hit, index) => (
                      <button
                        key={`${index}-${hit.label}`}
                        type="button"
                        onClick={() => hit.element.scrollIntoView({ block: "center" })}
                        className="block w-full truncate rounded-xl px-3 py-1.5 text-left text-[13px] text-fg/75 hover:bg-surface-2 hover:text-fg"
                      >
                        {hit.label}
                      </button>
                    ))}
                  </>
                )}
                {hits.length === 0 && pageHits.length === 0 && <div className="px-3 py-1.5 text-[13px] text-muted">{t("Nothing matches")}</div>}
              </div>
            )}
            {sections.map((sec) => (
              <button
                key={sec.id}
                type="button"
                onClick={() => document.getElementById(sec.id)?.scrollIntoView({ behavior: "smooth", block: "start" })}
                className={cx(
                  "truncate rounded-xl px-3 py-1.5 text-left text-[13px] font-medium text-fg/75 hover:bg-surface-2 hover:text-fg",
                  searching && matching.has(sec.id) && "bg-accent/10 text-fg",
                )}
              >
                {sec.title}
              </button>
            ))}
          </nav>
        )}
      <div ref={bodyRef} className="flex-1 overflow-y-auto px-4 pb-8 space-y-5">
        {/* who it is */}
        {show("who") && (
        <Section title={name} id="who" plain={!wide}>
          <IdentityForm
            value={identity}
            onChange={setIdentity}
            suggestions={false}
            inputCls={settingsInput}
            onStudio={() => setTab("avatar")}
          />
          <button
            type="button"
            disabled={!dirty || saving}
            onClick={() => void update({ profile: identityBody(identity) }, t("Saved"))}
            className="w-full rounded-2xl bg-accent text-accent-fg py-2.5 font-medium disabled:opacity-40"
          >
            {t("Save")}
          </button>
        </Section>
        )}

        {/* Sentinel */}
        {show("sentinel") && (
        <Section title={t("Safety · Sentinel")} id="sentinel" plain={!wide}>
          <p className="text-[13px] text-muted -mt-1">
            {t("A separate gatekeeper reviews every action. Pick how often it should check in with you.")}
          </p>
          <div className="space-y-2">
            {MODES.map((m) => (
              <button
                key={m.id}
                type="button"
                onClick={() => void update({ sentinel_mode: m.id })}
                aria-pressed={s?.sentinel.mode === m.id}
                className={cx(
                  "w-full text-left rounded-2xl border px-3.5 py-3 flex items-start gap-3 transition",
                  s?.sentinel.mode === m.id ? "border-accent bg-accent/8" : "border-border",
                )}
              >
                <div className={cx("mt-0.5", m.id === "auto" ? "text-rose-500" : "text-accent")}>{m.icon}</div>
                <div className="flex-1">
                  <div className="font-medium text-[14.5px]">{t(m.title)}</div>
                  <div className="text-[12.5px] text-muted leading-snug mt-0.5">{t(m.text)}</div>
                </div>
                {s?.sentinel.mode === m.id && <Check size={18} className="text-accent mt-0.5" />}
              </button>
            ))}
          </div>
          {s && (
            <div className="text-[12.5px] text-muted leading-relaxed">
              {t("Always asks before: {tools}.", { tools: s.sentinel.always_ask_tools.map((tool) => t(tool)).join(", ") || t("none") })}{" "}
              {s.sentinel.taint_tracking && t("After reading private data, new network destinations need approval.")}
            </div>
          )}
          {s?.sandbox && (
            <div className="flex items-start gap-2.5 rounded-2xl bg-surface-2/60 px-3.5 py-2.5 text-[12.5px] leading-snug">
              <Box size={15} className={cx("shrink-0 mt-[2px]", s.sandbox.active ? "text-emerald-500" : "text-muted")} />
              <div>
                <div className="font-medium text-fg">
                  {s.sandbox.active ? t("Commands run in a sandbox") : t("Commands run without a sandbox")}
                  <span className="text-muted font-normal"> · {s.sandbox.status}</span>
                </div>
                <div className="text-muted mt-0.5">
                  {s.sandbox.active
                    ? t("Each shell or Python call gets its own namespace: only the workspace is writable, your home directory is not there, and there is no network unless the command needs it.")
                    : s.sandbox.status.includes("container")
                      ? t("Each shell or Python call runs in the workspace with a scrubbed environment; the container is the boundary.")
                      : t("Each shell or Python call runs in the workspace with a scrubbed environment. On Linux, installing bubblewrap gives each one its own namespace.")}
                </div>
              </div>
            </div>
          )}
        </Section>
        )}

        {/* Proactivity */}
        {show("proactivity") && (
        <Section title={t("Proactivity")} id="proactivity" plain={!wide}>
          <ProactivityDial value={state.profile?.proactivity ?? "default"} onChange={(v) => void update({ profile: { proactivity: v } })} />
          <div className="flex items-center gap-3">
            <label htmlFor={intervalId} className="text-[13.5px] flex-1">
              {t("Check-in interval")}
              {state.profile && state.profile.proactivity !== "default" && state.profile.proactivity !== "off" && (
                <span className="block text-[12px] text-muted">
                  {state.profile.proactivity === "low" ? t("Doubled at this level") : t("Halved at this level")}
                </span>
              )}
            </label>
            <select
              id={intervalId}
              value={state.profile?.goal_interval_minutes ?? 60}
              onChange={(e) => void update({ profile: { goal_interval_minutes: Number(e.target.value) } })}
              className="rounded-2xl bg-surface-2 px-3 py-2 text-[13.5px] outline-none"
            >
              {[...new Set([15, 30, 60, 120, 240, 480, 1440, state.profile?.goal_interval_minutes ?? 60])]
                .sort((a, b) => a - b)
                .map((m) => (
                  <option key={m} value={m}>
                    {m < 60 ? t("{n} min", { n: m }) : m % 60 ? `${t("{n} h", { n: Math.floor(m / 60) })} ${t("{n} min", { n: m % 60 })}` : t("{n} h", { n: m / 60 })}
                  </option>
                ))}
            </select>
          </div>
          <QuietHours value={state.profile?.quiet_hours ?? ""} onChange={(v) => void update({ profile: { quiet_hours: v } })} />
        </Section>
        )}

        {/* Notifications */}
        {show("notifications") && (
        <Section title={t("Notifications")} id="notifications" plain={!wide}>
          {androidApp() ? <PhoneAppSettings name={state.profile?.name ?? "nanoMuse"} /> : <PushSettings name={state.profile?.name ?? "nanoMuse"} />}
        </Section>
        )}

        {/* Keep it running: only the Android app has anything to say here */}
        {keepRunningStatus() && show("keep-running") && (
          <Section title={t("Keep it running")} id="keep-running" plain={!wide}>
            <KeepRunningSettings name={state.profile?.name ?? "nanoMuse"} />
          </Section>
        )}

        {/* Model */}
        {show("model") && (
        <Section title={t("Model")} id="model" plain={!wide}>
          {s && (
            <button type="button" onClick={() => setTab("connections")} className="w-full text-[13.5px] flex items-center justify-between">
              <span className="text-muted">{t("Provider / model")}</span>
              <span className="font-mono text-[12.5px] flex items-center gap-1">
                {s.llm.model} <ChevronRight size={14} className="text-muted" />
              </span>
            </button>
          )}
          {s?.llm.cloud && (
            <button type="button" onClick={() => openOwnKeySetup(setTab, ownKeyWay(state.hub?.account).preset)} className="w-full text-[13.5px] flex items-center justify-between">
              <span className="text-muted">{t("Use my own API key or a plan I pay for")}</span>
              <span className="text-[12.5px] text-muted flex items-center gap-1">
                {t("{first} first, then {others}", { first: ownKeyWay(state.hub?.account).label, others: isMainland(state.hub?.account) ? t("DeepSeek, Kimi, OpenAI, ChatGPT…") : t("OpenAI, ChatGPT, Gemini, DeepSeek…") })} <ChevronRight size={14} />
              </span>
            </button>
          )}
          <button type="button" onClick={() => setTab("connections")} className="w-full text-[13.5px] flex items-center justify-between">
            <span className="text-muted">{t("Connections")}</span>
            <span className="text-[12.5px] text-muted flex items-center gap-1">
              {t("E-mail, calendar, browser, MCP servers")} <ChevronRight size={14} />
            </span>
          </button>
        </Section>
        )}

        {/* Appearance: this device's theme and language, the agent's reply language */}
        {show("appearance") && (
        <Section title={t("Appearance")} id="appearance" plain={!wide}>
          <Toggle
            label={t("Show the agent's steps")}
            hint={t("Every tool it uses becomes a chip in the chat. Off, the chat keeps to the conversation and the line under the name says what it is on. This device only.")}
            checked={steps}
            onChange={setShowSteps}
          />
          <Toggle
            label={t("Show thinking")}
            hint={t("Reveal the model's reasoning under each reply when the provider exposes it.")}
            checked={!!s?.agent.show_thinking}
            onChange={(v) => void update({ show_thinking: v })}
          />
          <div className="flex items-center gap-3">
            <label htmlFor={themeId} className="text-[13.5px] flex-1">
              {t("Appearance")}
              <span className="block text-[12px] text-muted">{t("This device only")}</span>
            </label>
            <select
              id={themeId}
              value={themeSetting}
              onChange={(e) => setThemeSetting(e.target.value as typeof themeSetting)}
              className="rounded-2xl bg-surface-2 px-3 py-2 text-[13.5px] outline-none"
            >
              <option value="light">{t("Light")}</option>
              <option value="dark">{t("Dark")}</option>
              <option value="system">{t("Follow the system")}</option>
            </select>
          </div>
          <div className="flex items-center gap-3">
            <label htmlFor={appLangId} className="text-[13.5px] flex-1">
              {t("App language")}
              <span className="block text-[12px] text-muted">{t("This device only")}</span>
            </label>
            <select
              id={appLangId}
              value={localeSetting}
              onChange={(e) => setLocaleSetting(e.target.value as typeof localeSetting)}
              className="rounded-2xl bg-surface-2 px-3 py-2 text-[13.5px] outline-none"
            >
              {LOCALES.map((l) => (
                <option key={l.value} value={l.value}>
                  {l.value === "auto" ? t("Auto") : l.label}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-3">
            <label htmlFor={replyLangId} className="text-[13.5px] flex-1">
              {t("Reply language")}
              <span className="block text-[12px] text-muted">{t("What {name} writes in", { name: state.profile?.name ?? "nanoMuse" })}</span>
            </label>
            <select
              id={replyLangId}
              value={s?.agent.language ?? "auto"}
              onChange={(e) => void update({ language: e.target.value })}
              className="rounded-2xl bg-surface-2 px-3 py-2 text-[13.5px] outline-none"
            >
              <option value="auto">{t("Match mine")}</option>
              <option value="English">English</option>
              <option value="中文">中文</option>
              <option value="日本語">日本語</option>
              <option value="Español">Español</option>
              <option value="Deutsch">Deutsch</option>
              <option value="Français">Français</option>
            </select>
          </div>
        </Section>
        )}

        {/* The desktop app's own switches: the shell around this page */}
        {isDesktopApp() && show("desktop") && (
          <Section title={t("Desktop app")} id="desktop" plain={!wide}>
            <DesktopAppSettings />
          </Section>
        )}

        {/* Data controls: the one switch over what the relay keeps, the shape of Muse's */}
        {show("data") && (
        <Section title={t("Data controls")} id="data" plain={!wide}>
          <DataControls flush />
        </Section>
        )}

        {/* The developer side, off unless asked for */}
        {show("developer") && (
        <Section title={t("Developer")} id="developer" plain={!wide}>
          <Toggle
            label={t("Developer tools")}
            hint={t("The Coding screen (Cursor, Codex and the other coding agents on this computer) in the sidebar, and the runtime's address below. This device only.")}
            checked={developer}
            onChange={setDeveloperTools}
          />
          {developer && (
            <div className="text-[13px] text-muted space-y-1">
              <div className="break-all">
                {t("Runtime:")} {window.location.origin} · <span className="text-fg/70">{t("the token is in the server_token file in the data folder")}</span>
              </div>
              <div>
                <a href="https://github.com/nano-muse/nanoMuse/blob/main/docs/cli.md" target="_blank" rel="noreferrer" className="text-accent underline-offset-2 hover:underline">
                  {t("The command line and the API")}
                </a>
                {" · "}
                <a href="https://github.com/nano-muse/nanoMuse/blob/main/docs/harness.md" target="_blank" rel="noreferrer" className="text-accent underline-offset-2 hover:underline">
                  {t("nanoMuse on DeepSeek Harness")}
                </a>
              </div>
            </div>
          )}
        </Section>
        )}

        {/* About */}
        {show("about") && (
        <Section title={t("About")} id="about" plain={!wide}>
          <CommunityNotice />
          <VersionRows installed={state.version} release={release} checking={checking} onCheck={() => void checkRelease(true)} />
          <div className="text-[13px] text-muted space-y-1">
            {s && <div className="break-all">{t("Data:")} {s.data_dir}</div>}
            {s && <div className="break-all">{t("Workspace:")} {s.agent.workspace}</div>}
            <div>{state.connected ? t("Connected") : t("Reconnecting…")}</div>
          </div>
          <button
            type="button"
            onClick={() => {
              const phone = androidApp();
              if (phone) {
                phone.disconnect();
                return;
              }
              setToken("");
              window.location.reload();
            }}
            className="w-full rounded-2xl border border-border py-2.5 text-[14px] font-medium flex items-center justify-center gap-2 text-muted"
          >
            <LogOut size={16} /> {androidApp() ? t("Disconnect from this server") : t("Forget this device's access token")}
          </button>
        </Section>
        )}
      </div>
      </div>
    </div>
  );
}

type SectionId = "who" | "sentinel" | "proactivity" | "notifications" | "keep-running" | "model" | "appearance" | "desktop" | "data" | "developer" | "about";
const SECTION_IDS: SectionId[] = ["who", "sentinel", "proactivity", "notifications", "keep-running", "model", "appearance", "desktop", "data", "developer", "about"];

/**
 * The Version card (contract C2): the installed release, and the latest one as the runtime
 * found it on nanomuse.cn/dl or GitHub — "you have it", "x is out" with Update, or "could
 * not check" with a try again. Permanent: both lines are there whatever the answer. A phone
 * shell checks on its own, so the latest line says so instead.
 */
function VersionRows({ installed, release, checking, onCheck }: { installed: string; release: UpdateView | null; checking: boolean; onCheck: () => void }) {
  const t = useT();
  const phone = Boolean(androidApp());
  const checkNow = (
    <button type="button" onClick={onCheck} disabled={checking} className="text-accent underline-offset-2 hover:underline disabled:opacity-60">
      {checking ? t("Checking…") : t("Check now")}
    </button>
  );
  let latest: ReactNode;
  if (phone) latest = t("The phone app checks for updates on its own.");
  else if (release && !release.enabled) latest = t("Update checks are off here.");
  else if (checking && !release) latest = t("Checking…");
  else if (release?.latest && release.newer)
    latest = (
      <>
        {t("{version} is out", { version: release.latest })}
        {" · "}
        <a href={release.download_url || release.url} target="_blank" rel="noreferrer" className="font-medium text-accent underline-offset-2 hover:underline">
          {t("Update")}
        </a>
      </>
    );
  else if (release?.latest) latest = <>{t("Latest {version}; you have it", { version: release.latest })} · {checkNow}</>;
  else latest = <>{t("Could not check")} · {checkNow}</>;
  return (
    <div className="rounded-2xl bg-surface-2/60 px-3.5 py-2.5 text-[13px]">
      <div className="font-medium">{t("nanoMuse {version}", { version: installed })}</div>
      <div className="mt-0.5 text-muted">{latest}</div>
      {!phone && release?.latest && release.newer && <div className="mt-1 text-[12px] text-muted">{t("To update: pip install -U nanomuse, pull the new image, or use the desktop app's Update.")}</div>}
      {!phone && release?.checked_at && <div className="mt-1 text-[12px] text-muted">{t("Checked {when}", { when: relativeTime(release.checked_at) })}</div>}
    </div>
  );
}

/**
 * The phone's Settings: Muse's bar, then white cards of outlined-glyph rows on the grey
 * canvas, grouped the way the Android app groups them — the model, the agent, how it
 * behaves, the app, about — each row opening its own page or screen.
 */
function SettingsHome({
  release,
  onOpen,
  sections,
  query,
  onQuery,
}: {
  release: UpdateView | null;
  onOpen: (id: SectionId) => void;
  sections: Array<{ id: SectionId; title: string }>;
  query: string;
  onQuery: (value: string) => void;
}) {
  const { state, setTab } = useStore();
  const t = useT();
  const s = state.settings;
  const hub = state.hub;
  // what the configured providers cover (contract C11), from the runtime; null on an older one
  const providers = useProviders();
  const name = state.profile?.name ?? "nanoMuse";
  const themeSetting = useThemeSetting();
  const others = hub?.devices.filter((d) => !d.this && d.kind !== "web") ?? [];
  const computers = others.filter((d) => d.kind === "computer");
  const coding = others.filter((d) => d.online && d.actions?.includes("coding.sessions"));
  const mode = s?.sentinel.mode;
  const modeLabel = mode === "ask" ? t("Balanced") : mode === "strict" ? t("Cautious") : mode === "auto" ? t("Hands-off") : "";
  const level = state.profile?.proactivity ?? "default";
  const levelLabel = level === "off" ? t("Off") : level === "low" ? t("Low") : level === "high" ? t("High") : t("Default");
  const themeLabel = themeSetting === "dark" ? t("Dark") : themeSetting === "light" ? t("Light") : t("Follow the system");
  const none = t("none");
  // The settings search on the phone: the sections by their title. Their words are
  // not rendered on this screen, so the title is all a query can answer here; the
  // query stands when a section opens, and its words are marked on that page.
  const homeSearching = queryWords(query).length > 0;
  const sectionHits = filterPages(
    sections.map((sec) => ({ id: sec.id, label: sec.title })),
    query,
  );
  const onHomeSearchKey = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") {
      if (query.trim() === "") return;
      event.preventDefault();
      onQuery("");
      return;
    }
    if (event.key !== "Enter") return;
    event.preventDefault();
    const first = sectionHits[0];
    if (first !== undefined) onOpen(first.id);
  };
  const searchBox = (
    <div className="px-4 pb-1 pt-1">
      <div className="flex items-center gap-2 rounded-xl bg-surface-2 px-2.5 py-2">
        <Search size={15} className="shrink-0 text-muted" />
        <input
          type="text"
          value={query}
          onChange={(e) => onQuery(e.currentTarget.value)}
          onKeyDown={onHomeSearchKey}
          placeholder={t("Search settings")}
          aria-label={t("Search settings")}
          className="w-full bg-transparent text-[13.5px] outline-none placeholder:text-muted"
        />
      </div>
    </div>
  );
  if (homeSearching) {
    return (
      <div className="flex h-full flex-col">
        <PageBar title={t("Settings")} />
        {searchBox}
        <div className="flex-1 overflow-y-auto px-4 pb-8 pt-2">
          {sectionHits.length > 0 ? (
            <MuseCard>
              {sectionHits.map((sec, index) => (
                <Fragment key={sec.id}>
                  {index > 0 && <MuseDivider />}
                  <MuseRow label={sec.label} onClick={() => onOpen(sec.id)} />
                </Fragment>
              ))}
            </MuseCard>
          ) : (
            <div className="px-1 pt-2 text-[13.5px] text-muted">{t("Nothing matches")}</div>
          )}
        </div>
      </div>
    );
  }
  return (
    <div className="flex h-full flex-col">
      <PageBar title={t("Settings")} />
      {searchBox}
      <div className="flex-1 overflow-y-auto pb-8 pt-2">
        {/* the model: where Muse's plan card stands */}
        <MuseCard className="mb-3">
          <button type="button" onClick={() => setTab("connections")} className="flex w-full items-center gap-3 px-4 py-3.5 text-left hover:bg-surface-2/60">
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[16px] font-medium leading-[21px]">{s?.llm.model || t("No model yet")}</span>
              <span className="mt-0.5 block truncate text-[12.5px] leading-4 text-muted">
                {s ? (s.llm.cloud ? "nanoMuse Cloud" : s.llm.provider) : t("Add a provider and pick its models")}
              </span>
            </span>
            <span className="text-[14px] font-medium text-accent">{t("Change")}</span>
          </button>
          <MuseDivider />
          <MuseRow icon={<Cloud size={22} />} label="nanoMuse Cloud" value={hub?.account.signed_in ? hub.account.hint : t("Sign in")} onClick={() => setTab("account")} />
          <MuseDivider />
          <MuseRow
            icon={<Clapperboard size={22} />}
            label={t("Image & video models")}
            value={
              has(providers, "image") === false
                ? unavailableLine(t, "image", regionOf(hub?.account), getLocale())
                : has(providers, "video") === false
                  ? unavailableLine(t, "video", regionOf(hub?.account), getLocale())
                  : undefined
            }
            onClick={() => setTab("connections")}
          />
          <MuseDivider />
          <MuseRow icon={<BarChart3 size={22} />} label={t("Usage")} onClick={() => setTab("account")} />
        </MuseCard>

        {/* the agent */}
        <MuseCard className="mb-3">
          <MuseRow icon={<Sparkles size={22} />} label={t("Name & personality")} value={name} onClick={() => onOpen("who")} />
          <MuseDivider />
          <MuseRow icon={<Smile size={22} />} label={t("Avatar")} onClick={() => setTab("avatar")} />
          <MuseDivider />
          <MuseRow icon={<Brain size={22} />} label={t("Memory")} onClick={() => setTab("memory")} />
          {s?.skills?.enabled !== false && (
            <>
              <MuseDivider />
              <MuseRow icon={<Puzzle size={22} />} label={t("Skills")} value={s ? String(s.skills.count) : undefined} onClick={() => setTab("skills")} />
            </>
          )}
          <MuseDivider />
          <MuseRow icon={<Plug size={22} />} label={t("Connections")} value={s?.connectors.mcp.length ? `${s.connectors.mcp.length} MCP` : undefined} onClick={() => setTab("connections")} />
          <MuseDivider />
          <MuseRow icon={<MessageSquare size={22} />} label={t("Chat apps")} onClick={() => setTab("channels")} />
          <MuseDivider />
          <MuseRow icon={<Monitor size={22} />} label={t("Devices")} value={computers.length ? String(computers.length) : none} onClick={() => setTab("devices")} />
          <MuseDivider />
          <MuseRow icon={<TerminalSquare size={22} />} label={t("Coding agents")} value={coding.length ? String(coding.length) : none} onClick={() => setTab("coding")} />
        </MuseCard>

        {/* how it behaves */}
        <MuseCard className="mb-3">
          <MuseRow icon={<ShieldCheck size={22} />} label={t("Safety · Sentinel")} value={modeLabel} onClick={() => onOpen("sentinel")} />
          <MuseDivider />
          <MuseRow icon={<Zap size={22} />} label={t("Proactivity")} value={levelLabel} onClick={() => onOpen("proactivity")} />
          <MuseDivider />
          <MuseRow icon={<Bell size={22} />} label={t("Notifications")} onClick={() => onOpen("notifications")} />
          {keepRunningStatus() && (
            <>
              <MuseDivider />
              <MuseRow icon={<BatteryFull size={22} />} label={t("Keep it running")} onClick={() => onOpen("keep-running")} />
            </>
          )}
        </MuseCard>

        {/* the app */}
        <MuseCard className="mb-3">
          <MuseRow icon={<Palette size={22} />} label={t("Appearance")} value={themeLabel} onClick={() => onOpen("appearance")} />
          {isDesktopApp() && (
            <>
              <MuseDivider />
              <MuseRow icon={<Monitor size={22} />} label={t("Desktop app")} onClick={() => onOpen("desktop")} />
            </>
          )}
          <MuseDivider />
          <MuseRow icon={<DatabaseZap size={22} />} label={t("Data controls")} onClick={() => onOpen("data")} />
          <MuseDivider />
          <MuseRow icon={<Code2 size={22} />} label={t("Developer")} onClick={() => onOpen("developer")} />
        </MuseCard>

        {/* about */}
        <MuseCard className="mb-3">
          <MuseRow icon={<Info size={22} />} label={t("About nanoMuse")} value={release?.newer && release.latest ? t("{version} is out", { version: release.latest }) : undefined} onClick={() => onOpen("about")} />
          <MuseDivider />
          <MuseRow icon={<Hand size={22} />} label={t("Privacy policy")} onClick={() => window.open(PRIVACY_URL, "_blank", "noopener")} external />
          <MuseDivider />
          <MuseRow icon={<MessageSquareWarning size={22} />} label={t("Feedback")} onClick={() => window.open("https://github.com/nano-muse/nanoMuse/issues/new/choose", "_blank", "noopener")} external />
        </MuseCard>
        <MuseCaption>nanoMuse {state.version}</MuseCaption>
      </div>
    </div>
  );
}

/** Inside the Android app: the app's own background connection stands in for Web Push. */
function PhoneAppSettings({ name }: { name: string }) {
  const t = useT();
  const phone = androidApp();
  const [on, setOn] = useState(() => phone?.notificationsEnabled() ?? false);
  if (!phone) return null;
  return (
    <>
      <Toggle
        label={t("Let {name} notify this phone", { name })}
        hint={t("The app stays connected to your server in the background. Approvals, questions and finished background work arrive as notifications and open the right chat.")}
        checked={on}
        onChange={(v) => {
          phone.setNotificationsEnabled(v);
          setOn(v);
        }}
      />
      <div className="text-[12.5px] text-muted">{t("nanoMuse for Android {version}", { version: phone.version() })}</div>
    </>
  );
}

/**
 * The Android switches that decide whether the agent keeps running with the screen off —
 * battery, overlay, exact alarms, start on boot — plus the vendor's own, and the log export.
 */
function KeepRunningSettings({ name }: { name: string }) {
  const t = useT();
  const app = androidApp();
  const [st, setSt] = useState<KeepRunningStatus | null>(keepRunningStatus);
  useEffect(() => {
    // the user comes back from a settings page: read again
    const again = () => setSt(keepRunningStatus());
    document.addEventListener("visibilitychange", again);
    window.addEventListener("focus", again);
    return () => {
      document.removeEventListener("visibilitychange", again);
      window.removeEventListener("focus", again);
    };
  }, []);
  if (!app || !st) return null;
  const open = (what: string) => app.openKeepRunning?.(what);
  const vendorTips: Record<string, string> = {
    xiaomi: t("Xiaomi / Redmi / POCO: Settings → Apps → Manage apps → {name} → Autostart on; Battery saver → No restrictions; Other permissions → Display pop-up windows while running in the background on."),
    huawei: t("Huawei: Settings → Battery → App launch → {name} → Manage manually, all three on (auto-launch, secondary launch, run in background); Settings → Apps → {name} → Battery → Launch: manage manually."),
    honor: t("Honor: Settings → Battery → App launch → {name} → Manage manually, all three on; Battery → More battery settings → Stay connected while asleep on."),
    oppo: t("OPPO / realme / OnePlus: Settings → Battery → More settings → Optimise battery use → {name} → Don't optimise; Settings → Apps → {name} → Battery usage → Allow background activity, Allow auto launch."),
    vivo: t("vivo / iQOO: i Manager → App manager → Autostart → {name} on; Settings → Battery → Background power consumption management → {name} → Allow high background power consumption."),
    samsung: t("Samsung: Settings → Battery → Background usage limits → {name} not in Sleeping or Deep sleeping apps (add it to Never sleeping apps); turn off Adaptive battery if it keeps stopping."),
    meizu: t("Meizu: Settings → Apps → {name} → Background management → Keep running in the background; Battery → App power management → Allow."),
  };
  const tip = vendorTips[st.vendor];
  return (
    <>
      <p className="text-[12.5px] text-muted leading-snug">
        {t("Android stops apps that seem idle. {name} runs as a foreground service and holds the phone awake only while a task runs; these switches let it keep that promise on this phone.", { name })}
      </p>
      <Row
        label={t("Battery")}
        value={st.battery_unrestricted ? t("Unrestricted") : t("Optimised")}
        ok={st.battery_unrestricted}
        hint={t("Optimised means Android may freeze the agent after a while with the screen off; routines and check-ins then wait until the phone wakes.")}
        action={st.battery_unrestricted ? undefined : { label: t("Allow"), onClick: () => open("battery") }}
      />
      <Row
        label={t("Display over other apps")}
        value={st.overlay ? t("Allowed") : t("Not allowed")}
        ok={st.overlay}
        hint={t("Lets the agent bring an app to the front from the background and show its status capsule while it works in other apps.")}
        action={st.overlay ? undefined : { label: t("Allow"), onClick: () => open("overlay") }}
      />
      {st.exact_alarms !== "n/a" && st.local && (
        <Row
          label={t("Alarms & reminders")}
          value={st.exact_alarms === "granted" ? t("Exact") : t("Approximate")}
          ok={st.exact_alarms === "granted"}
          hint={t("With exact alarms a reminder fires at the minute you named even when the phone is asleep; without them Android may deliver it up to a quarter of an hour late.")}
          action={st.exact_alarms === "granted" ? undefined : { label: t("Allow"), onClick: () => open("alarms") }}
        />
      )}
      <Toggle
        label={t("Start after a reboot")}
        hint={st.local ? t("Bring the runtime back when the phone restarts, so routines and check-ins do not stop.") : t("Reconnect to your computer when the phone restarts, so approvals keep arriving.")}
        checked={st.boot_start}
        onChange={(v) => {
          app.setStartOnBoot?.(v);
          setSt({ ...st, boot_start: v });
        }}
      />
      {tip && (
        <div className="rounded-2xl bg-surface-2 px-3 py-2.5 text-[12.5px] leading-snug space-y-2">
          <div className="font-medium">{t("On this phone's Android")}</div>
          <div className="text-muted">{tip}</div>
          {st.autostart_settings && (
            <button type="button" onClick={() => open("autostart")} className="rounded-full border border-border px-3 py-1.5 text-[12.5px]">
              {t("Open the auto-start settings")}
            </button>
          )}
        </div>
      )}
      <div className="flex items-center justify-between gap-3 pt-1">
        <div className="text-[12.5px] text-muted leading-snug">{t("Crashes are written to a file on this phone and nowhere else. Export bundles them with the runtime's log for someone you choose.")}</div>
        <button type="button" onClick={() => app.exportLogs?.()} className="shrink-0 rounded-full border border-border px-3 py-1.5 text-[12.5px]">
          {t("Export logs")}
        </button>
      </div>
    </>
  );
}

function Row({
  label,
  value,
  ok,
  hint,
  action,
}: {
  label: string;
  value: string;
  ok: boolean;
  hint?: string;
  action?: { label: string; onClick: () => void };
}) {
  return (
    <div className="flex items-start gap-3">
      <div className="flex-1">
        <div className="flex items-center gap-2 text-[14px]">
          <span>{label}</span>
          <span className={cx("rounded-full px-2 py-0.5 text-[11px] font-medium", ok ? "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300" : "bg-amber-500/15 text-amber-700 dark:text-amber-300")}>{value}</span>
        </div>
        {hint && <div className="text-[12.5px] text-muted leading-snug">{hint}</div>}
      </div>
      {action && (
        <button type="button" onClick={action.onClick} className="shrink-0 rounded-full bg-accent px-3 py-1.5 text-[12.5px] font-medium text-white">
          {action.label}
        </button>
      )}
    </div>
  );
}

/** Web Push: on / off, what stands in the way, and a test button. */
function PushSettings({ name }: { name: string }) {
  const { toast } = useStore();
  const [info, setInfo] = useState<PushInfo | null>(null);
  const [status, setStatus] = useState<PushState>("off");
  const [busy, setBusy] = useState(false);
  const t = useT();

  const refresh = async () => {
    setStatus(await pushState());
    try {
      setInfo(await api.push());
    } catch {
      /* older server */
    }
  };
  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggle = async () => {
    if (!info) return;
    setBusy(true);
    try {
      const next = status === "on" ? await disablePush() : await enablePush(info.public_key);
      setStatus(next);
      if (next === "denied") toast(t("Notifications are blocked for this site in the browser settings"));
      await refresh();
    } catch (e) {
      const err = e as Error;
      toast(
        err.name === "AbortError"
          ? t("This browser has no push service (embedded browsers often don't). Use Chrome, Edge, Firefox or Safari 16.4+ on the phone.")
          : err.message,
      );
    } finally {
      setBusy(false);
    }
  };

  const test = async () => {
    try {
      const r = await api.pushTest();
      toast(r.ok ? t("Sent. It should arrive in a moment") : r.error ?? t("Could not send"));
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const blocked =
    status === "unsupported"
      ? t("This browser cannot receive push notifications.")
      : status === "insecure"
        ? t("Notifications need https:// (or localhost). Over plain http on your LAN the app works, this part stays off; see docs/deployment.md.")
        : status === "denied"
          ? t("Blocked for this site. Allow notifications in the browser's site settings, then try again.")
          : info && !info.available
            ? t("The server was installed without pywebpush.")
            : "";

  return (
    <>
      <Toggle
        label={t("Let {name} notify this device", { name })}
        hint={t("Approvals, questions, finished background work and check-ins; nothing while the app is on screen.")}
        checked={status === "on"}
        onChange={() => void toggle()}
        disabled={busy || !!blocked}
      />
      {blocked && <div className="text-[12.5px] text-muted">{blocked}</div>}
      {info && info.subscriptions > 0 && (
        <div className="flex items-center justify-between text-[12.5px] text-muted">
          <span>
            {info.subscriptions === 1 ? t("1 device subscribed") : t("{n} devices subscribed", { n: info.subscriptions })}
          </span>
          <button type="button" onClick={() => void test()} className="text-accent font-medium">
            {t("Send a test")}
          </button>
        </div>
      )}
      {!isDesktopApp() && (
        <div className="text-[12.5px] text-muted">{t("On a phone, add the app to the home screen first; the icon then shows a badge and notifications open the right chat.")}</div>
      )}
    </>
  );
}

const LEVELS: Array<{ id: Proactivity; title: string; text: string }> = [
  { id: "off", title: "Off", text: "Only works when you ask." },
  { id: "low", title: "Low", text: "Checks in half as often; speaks up only when a step is done or it needs you." },
  { id: "default", title: "Default", text: "Works on goals on schedule; reports real progress, stays quiet otherwise." },
  { id: "high", title: "High", text: "Checks in twice as often and always reports, even 'still on track'." },
];

export function ProactivityDial({ value, onChange }: { value: Proactivity; onChange: (v: Proactivity) => void }) {
  const t = useT();
  const current = LEVELS.find((l) => l.id === value) ?? LEVELS[2];
  return (
    <div>
      <div className="flex items-center gap-3">
        <div className="flex-1 text-[13px] text-muted leading-snug">{t(current.text)}</div>
      </div>
      <div className="mt-2 grid grid-cols-4 gap-1 rounded-2xl bg-surface-2 p-1">
        {LEVELS.map((l) => (
          <button
            key={l.id}
            type="button"
            onClick={() => onChange(l.id)}
            aria-pressed={value === l.id}
            className={cx(
              "rounded-xl py-1.5 text-[13px] font-medium transition",
              value === l.id ? "bg-surface shadow-sm text-accent" : "text-muted",
            )}
          >
            {t(l.title)}
          </button>
        ))}
      </div>
    </div>
  );
}

export function QuietHours({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [start, end] = value ? value.split("-") : ["", ""];
  const on = !!value;
  const t = useT();
  const set = (s: string, e: string) => onChange(s && e ? `${s}-${e}` : "");
  return (
    <div>
      <label className="flex items-start gap-3 cursor-pointer">
        <div className="flex-1">
          <div className="text-[14px] flex items-center gap-1.5">
            <Moon size={15} className="text-muted" /> {t("Quiet hours")}
          </div>
          <div className="text-[12.5px] text-muted leading-snug">{t("No background work in this window; anything due waits until it ends.")}</div>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={on}
          onClick={() => set(on ? "" : "22:00", on ? "" : "08:00")}
          className={cx("relative mt-0.5 h-7 w-12 shrink-0 rounded-full transition", on ? "bg-accent" : "bg-surface-2 border border-border")}
        >
          <span className={cx("absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition", on ? "left-[22px]" : "left-0.5")} />
        </button>
      </label>
      {on && (
        <div className="mt-2 flex items-center gap-2 text-[13.5px]">
          <span className="text-muted">{t("From")}</span>
          <input type="time" value={start} onChange={(e) => set(e.target.value, end)} aria-label={t("Quiet hours start")} className="rounded-xl bg-surface-2 px-2.5 py-1.5 outline-none" />
          <span className="text-muted">{t("to")}</span>
          <input type="time" value={end} onChange={(e) => set(start, e.target.value)} aria-label={t("Quiet hours end")} className="rounded-xl bg-surface-2 px-2.5 py-1.5 outline-none" />
        </div>
      )}
    </div>
  );
}

/** The Electron shell's switches (desktop/app/src/main/index.ts): start with the computer, the shortcuts. */
function DesktopAppSettings() {
  const t = useT();
  const bridge = desktopBridge();
  const [openAtLogin, setOpenAtLogin] = useState<boolean | null>(null);
  useEffect(() => {
    let live = true;
    void bridge?.loginItem?.().then((v) => {
      if (live) setOpenAtLogin(v);
    });
    return () => {
      live = false;
    };
  }, [bridge]);
  const mac = bridge?.platform === "darwin";
  const shortcuts: Array<[string, string]> = [
    [t("Quick chat"), mac ? "⌥ Space" : "Ctrl+Shift+Space"],
    [t("Show the window"), mac ? "⌘⇧M" : "Ctrl+Shift+M"],
    [t("Stop the hands"), mac ? "⌘⇧Esc" : "Ctrl+Shift+Esc"],
  ];
  return (
    <>
      {bridge?.setLoginItem && openAtLogin !== null && bridge.platform !== "linux" && (
        <Toggle
          label={t("Start with the computer")}
          hint={t("Opens in the tray at sign-in; the agent's goals and check-ins run from then on.")}
          checked={openAtLogin}
          onChange={(v) => {
            setOpenAtLogin(v);
            bridge.setLoginItem?.(v);
          }}
        />
      )}
      <div className="text-[13.5px]">
        {t("In the tray")}
        <span className="block text-[12px] text-muted">{t("The icon by the clock shows what the hands are doing and has Stop; closing the window keeps the agent running.")}</span>
      </div>
      <div className="space-y-1">
        <div className="text-[13.5px]">{t("Shortcuts")}</div>
        {shortcuts.map(([label, keys]) => (
          <div key={label} className="flex items-center justify-between text-[13px]">
            <span className="text-muted">{label}</span>
            <kbd className="rounded-md border border-border bg-surface-2 px-1.5 py-0.5 font-sans text-[12px] text-fg/80">{keys}</kbd>
          </div>
        ))}
      </div>
    </>
  );
}

/** A settings card; `plain` is the phone's page, where the bar above already names it. */
function Section({ title, children, id, plain = false }: { title: string; children: ReactNode; id?: string; plain?: boolean }) {
  return (
    <section id={id} className={cx("space-y-3 scroll-mt-4", plain ? "pt-1" : "rounded-3xl bg-surface border border-border/70 shadow-sm p-4")}>
      {!plain && <h2 className="text-[12px] font-semibold uppercase tracking-wide text-muted">{title}</h2>}
      {children}
    </section>
  );
}

