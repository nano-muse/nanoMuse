import { ArrowRight, Check, ChevronRight, Cloud, Loader2, Lock } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import { DRAGON } from "../avatars";
import { Avatar } from "../components/Avatar";
import { NOTICE_URL } from "../components/CommunityNotice";
import { AVATAR_COLORS } from "../components/AvatarPicker";
import { SignIn } from "../components/SignIn";
import { identityOf } from "../components/IdentityForm";
import { getLocale, useT } from "../i18n";
import { useStore } from "../store";
import { ownKeyLine } from "../region";
import type { ConnectionsData } from "../types";
import { cx } from "../util";
import { CalendarCard, ContactsCard, EmailCard, ModelCard, primaryBtn, secondaryBtn } from "./ConnectionsScreen";

type Step = "welcome" | "list" | "model" | "connect";

/**
 * First run: give it a model, start. A short list in that order — done items ticked, the
 * start locked until a model answers — and three optional connections under it. The
 * naming is not a form here: Start opens the chat, where the agent introduces itself and
 * asks what to call you, then picks its own name with you (the first conversation,
 * contract C4; `nanomuse/server/firstrun.py`). Everything else can be changed later under
 * the avatar (Settings, Connections).
 */
export function Onboarding() {
  const { state, setTab, dismissOnboarding, refreshSettings, toast } = useStore();
  const [step, setStep] = useState<Step>("welcome");
  const [conn, setConn] = useState<ConnectionsData | null>(null);
  const [starting, setStarting] = useState(false);
  const [cloudBusy, setCloudBusy] = useState(false);
  const t = useT();

  const pickCloudModel = async () => {
    setCloudBusy(true);
    try {
      await api.cloudUseAsModel();
      toast(t("The Cloud model is in use."));
      await loadConn();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setCloudBusy(false);
    }
  };

  const [connError, setConnError] = useState<string | null>(null);
  const loadConn = async () => {
    try {
      setConnError(null);
      setConn(await api.connections());
    } catch (e) {
      setConnError(t((e as Error).message) || t("Could not load the connections."));
    }
  };
  useEffect(() => {
    void loadConn();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload when the server says connections changed
  }, [state.connectionsVersion]);

  /** "Skip setup": the first run is over, without the first conversation. */
  const finish = async () => {
    try {
      await api.onboarded(true);
      await refreshSettings();
    } catch {
      /* the server remembers next time */
    }
    dismissOnboarding();
    setTab("chat");
  };

  /**
   * Start: the runtime binds the first conversation to the main chat and marks the first
   * run done; the chat then speaks its opening lines. An older runtime without the route
   * just gets the plain "onboarded".
   */
  const start = async () => {
    setStarting(true);
    try {
      await api.firstrunStart(getLocale() === "zh-CN" ? "zh" : "en");
    } catch {
      await api.onboarded(true).catch(() => undefined);
    }
    try {
      await refreshSettings();
    } catch {
      /* the hello snapshot carries it */
    }
    setStarting(false);
    dismissOnboarding();
    setTab("chat");
  };

  const identity = identityOf(state.profile, DRAGON, AVATAR_COLORS[0]);
  const preview = { ...identity, proactivity: "default" as const, proactive: true, goal_interval_minutes: 60, quiet_hours: "" };
  const modelReady = conn ? conn.llm.key_source === "vault" || conn.llm.key_source === "config" || !!conn.providers[presetOf(conn)]?.no_key : false;
  const connected = !!conn && (conn.email.configured || conn.calendar.feeds.length > 0 || conn.contacts.sources.length > 0);
  const progress: Step[] = ["welcome", "list"];
  const idx = step === "welcome" ? 0 : 1;

  return (
    <div className="mx-auto flex h-[100dvh] max-w-[760px] flex-col bg-bg sm:border-x sm:border-border">
      <div className="titlebar-room" />
      <header className="safe-top shrink-0 px-5 pt-4 pb-2 flex items-center justify-between">
        <div className="flex gap-1">
          {progress.map((s, i) => (
            <span key={s} className={cx("h-1.5 rounded-full transition-all", i <= idx ? "w-5 bg-accent" : "w-1.5 bg-border")} />
          ))}
        </div>
        <button type="button" onClick={() => void finish()} className="text-[13px] text-muted">
          {t("Skip setup")}
        </button>
      </header>

      <div className="flex-1 overflow-y-auto px-5 pb-6">
        {step === "welcome" && (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <Avatar profile={preview} size={96} />
            <h1 className="mt-6 text-[28px] font-bold tracking-tight">{t("Meet your nanoMuse")}</h1>
            <p className="mt-2 text-[15px] text-muted">{t("A personal agent of your own. Three things to know:")}</p>
            <ul className="mt-6 w-full max-w-sm space-y-2.5 text-left">
              <Point n={1} title={t("It does things for you.")} body={t("Searches, browses, writes, books, reads mail, and hands you the result, not a list of links.")} />
              <Point n={2} title={t("It keeps working when you close the app.")} body={t("Goals move forward between your visits; it reports in the Feed and notifies you when something is worth it.")} />
              <Point n={3} title={t("It asks you first where it matters.")} body={t("A separate Sentinel reviews every action. Sending, paying, deleting: it stops and asks; your keys stay in a vault the model cannot read.")} />
            </ul>
            <p className="mt-5 max-w-sm text-[13px] text-muted">{t("There is no form to fill in: once it has a model, it introduces itself in the chat and asks what to call you.")}</p>
            {/* the community line the sign-in gate says, for a runtime that does not ask for an account */}
            <p className="mt-2 max-w-sm text-[13px] text-muted">
              <a href={NOTICE_URL} target="_blank" rel="noreferrer" className="underline decoration-dotted underline-offset-2 hover:text-accent">
                {t("nanoMuse is a non-profit open-source community project, free forever.")}
              </a>
            </p>
          </div>
        )}

        {step === "list" && (
          <div className="pt-6">
            <div className="flex items-center gap-3">
              <Avatar profile={preview} size={56} />
              <div className="min-w-0">
                <h1 className="text-[24px] font-bold tracking-tight truncate">{t("Set it up")}</h1>
                <p className="text-[13.5px] text-muted truncate">{t("A model, then the chat. A minute.")}</p>
              </div>
            </div>
            <ol className="mt-6 space-y-2">
              <Item
                done={modelReady}
                title={t("Add a model")}
                body={
                  modelReady
                    ? conn?.llm.cloud
                      ? `nanoMuse Cloud · ${conn.llm.model}`
                      : `${conn?.llm.model} · ${hostOf(conn?.llm.base_url ?? "")}`
                    : state.hub?.account.signed_in
                      ? t("Your account's model, or a key of your own.")
                      : t("Pick a provider and paste a key. Yours, stored in the vault.")
                }
                onClick={() => setStep("model")}
              />
              <Item done={connected} optional title={t("Connect mail, calendar, contacts")} body={connected ? t("Connected. Tap to add more.") : t("Optional. It can read what came in, know your day, and who is who.")} onClick={() => setStep("connect")} />
              <Item locked={!modelReady} done={false} title={t("Start")} body={modelReady ? t("Open the chat. It introduces itself and asks your name.") : t("Needs a model first.")} onClick={() => modelReady && !starting && void start()} />
            </ol>
          </div>
        )}

        {step === "model" && (
          <div className="pt-6 space-y-4">
            <div>
              <h1 className="text-[26px] font-bold tracking-tight">{t("The model behind it")}</h1>
              <p className="mt-1 text-[14px] text-muted">
                {modelReady
                  ? conn?.llm.cloud
                    ? t("Your account's model, with its free allowance. Keep it, or switch to a key of your own here.")
                    : t("A model is already set up on the server. Keep it, or switch here.")
                  : t("Your account brings a model with a free allowance, nothing to set up. Or paste a key of your own; it is stored encrypted in the vault on the server, never shown to the model, and nothing you say passes through the relay.")}
              </p>
            </div>
            {conn ? (
              <>
                {!modelReady && state.hub?.account.signed_in && (
                  <button
                    type="button"
                    disabled={cloudBusy}
                    onClick={() => void pickCloudModel()}
                    className="flex w-full items-center gap-3 rounded-3xl border border-accent/30 bg-accent/5 px-4 py-3.5 text-left"
                  >
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-accent text-white">
                      {cloudBusy ? <Loader2 size={18} className="animate-spin" /> : <Cloud size={18} />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-[15px] font-medium">{t("Use the nanoMuse Cloud model")}</span>
                      <span className="block text-[12.5px] text-muted">{t("Signed in as {hint}. A free allowance, nothing to paste. Recommended to start.", { hint: state.hub.account.hint })}</span>
                    </span>
                    <ChevronRight size={16} className="shrink-0 text-muted" />
                  </button>
                )}
                {!modelReady && !state.hub?.account.signed_in && (
                  <div className="rounded-3xl border border-border/70 bg-surface p-4">
                    <SignIn onSignedIn={() => void loadConn()} useAsModel />
                  </div>
                )}
                {!modelReady && (
                  <p className="px-1 text-[12.5px] text-muted">
                    <span className="font-medium">{t("Or bring your own key")}</span> · {ownKeyLine(t, state.hub?.account)}
                  </p>
                )}
                <ModelCard data={conn} onChange={() => void loadConn()} compact />
              </>
            ) : connError ? (
              <div className="rounded-3xl border border-border/70 bg-surface p-4 text-center">
                <p className="text-[13.5px] text-muted">{connError}</p>
                <button type="button" onClick={() => void loadConn()} className="mt-3 rounded-full bg-surface-2 px-4 py-1.5 text-[13px] font-medium">
                  {t("Retry")}
                </button>
              </div>
            ) : (
              <div className="flex justify-center py-8 text-muted">
                <Loader2 className="animate-spin" size={20} />
              </div>
            )}
          </div>
        )}

        {step === "connect" && (
          <div className="pt-6 space-y-4">
            <div>
              <h1 className="text-[26px] font-bold tracking-tight">{t("Connect your mail, calendar and contacts")}</h1>
              <p className="mt-1 text-[14px] text-muted">
                {t("Optional. With a mailbox connected it can read what came in and draft replies; it will always ask before sending. With a calendar it knows your day and finds free time. With your contacts it knows who is who. The browser and MCP servers are under Connections later.")}
              </p>
            </div>
            {conn ? (
              <>
                <EmailCard data={conn} onChange={() => void loadConn()} compact />
                <CalendarCard data={conn} onChange={() => void loadConn()} compact />
                <ContactsCard data={conn} onChange={() => void loadConn()} compact />
              </>
            ) : connError ? (
              <div className="rounded-3xl border border-border/70 bg-surface p-4 text-center">
                <p className="text-[13.5px] text-muted">{connError}</p>
                <button type="button" onClick={() => void loadConn()} className="mt-3 rounded-full bg-surface-2 px-4 py-1.5 text-[13px] font-medium">
                  {t("Retry")}
                </button>
              </div>
            ) : (
              <div className="flex justify-center py-8 text-muted">
                <Loader2 className="animate-spin" size={20} />
              </div>
            )}
          </div>
        )}

      </div>

      <footer className="safe-bottom shrink-0 px-5 pb-5 pt-2 flex gap-2">
        {(step === "model" || step === "connect") && (
          <button type="button" onClick={() => setStep("list")} className={secondaryBtn}>
            {t("Back")}
          </button>
        )}
        {step === "welcome" && (
          <button type="button" onClick={() => setStep("list")} className={cx(primaryBtn, "flex-1 py-3")}>
            {t("Get started")} <ArrowRight size={16} />
          </button>
        )}
        {step === "list" && (
          <button type="button" disabled={!modelReady || starting} onClick={() => void start()} className={cx(primaryBtn, "flex-1 py-3")}>
            {starting ? <Loader2 size={16} className="animate-spin" /> : null} {modelReady ? t("Start") : t("Add a model to start")} <ArrowRight size={16} />
          </button>
        )}
        {step === "model" && (
          <button type="button" disabled={!modelReady} onClick={() => setStep("list")} className={cx(primaryBtn, "flex-1 py-3")}>
            {modelReady ? t("Done") : t("Save a model to continue")} <ArrowRight size={16} />
          </button>
        )}
        {step === "connect" && (
          <button type="button" onClick={() => setStep("list")} className={cx(primaryBtn, "flex-1 py-3")}>
            {connected ? t("Done") : t("Skip for now")} <ArrowRight size={16} />
          </button>
        )}
      </footer>
    </div>
  );
}

function Point({ n, title, body }: { n: number; title: string; body: string }) {
  return (
    <li className="flex gap-3 rounded-3xl bg-surface border border-border/70 p-4">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent/12 text-[13px] font-semibold text-accent">{n}</span>
      <div className="text-[13.5px] leading-relaxed">
        <div className="font-medium text-fg">{title}</div>
        <div className="text-muted">{body}</div>
      </div>
    </li>
  );
}

/** One row of the first-run list: ticked when done, greyed and locked until it can be done. */
function Item({ done, locked, optional, title, body, onClick }: { done: boolean; locked?: boolean; optional?: boolean; title: string; body: ReactNode; onClick: () => void }) {
  const t = useT();
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        disabled={locked}
        aria-disabled={locked}
        className={cx("w-full flex items-center gap-3 rounded-3xl border px-4 py-3.5 text-left transition-colors", done ? "border-accent/30 bg-accent/5" : "border-border/70 bg-surface", locked && "opacity-50")}
      >
        <span className={cx("flex h-7 w-7 shrink-0 items-center justify-center rounded-full", done ? "bg-accent text-white" : locked ? "bg-surface-2 text-muted" : "border border-border text-muted")}>
          {done ? <Check size={15} strokeWidth={3} /> : locked ? <Lock size={13} /> : null}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2 text-[15px] font-medium">
            <span className="truncate">{title}</span>
            {optional && <span className="rounded-full bg-surface-2 px-2 py-0.5 text-[10.5px] font-medium text-muted">{t("optional")}</span>}
          </span>
          <span className="block truncate text-[12.5px] text-muted">{body}</span>
        </span>
        {!locked && <ChevronRight size={16} className="shrink-0 text-muted" />}
      </button>
    </li>
  );
}

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

function presetOf(conn: ConnectionsData): string {
  const hit = Object.entries(conn.providers).find(([id, p]) => id !== "custom" && p.base_url && conn.llm.base_url.startsWith(p.base_url));
  return hit?.[0] ?? "custom";
}
