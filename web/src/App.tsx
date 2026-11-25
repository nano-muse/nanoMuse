import { LayoutGrid, Lightbulb, Loader2, MessageCircle, Newspaper, SquareCheckBig, WifiOff } from "lucide-react";
import { lazy, Suspense, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, setToken } from "./api";
import { BrandMark } from "./components/BrandMark";
import { DesktopRemoteHint } from "./components/DesktopRemoteHint";
import { ChatsDrawer } from "./components/ChatsDrawer";
import { FileViewer } from "./components/FileViewer";
import { FirstSignInSteps, useFirstSignIn } from "./components/FirstSignInSteps";
import { desktopBridge } from "./desktop";
import { Sidebar } from "./components/Sidebar";
import { ChatScreen } from "./screens/ChatScreen";
import { FeedScreen } from "./screens/FeedScreen";
import { SignInGate } from "./screens/SignInGate";
import { signInDoorNeeded } from "./gate";
import { useStore, type Tab } from "./store";
import { useT } from "./i18n";
import { cx } from "./util";

// The chat and the feed are what opens first; every other screen arrives as its own chunk
// the first time it is shown, so the first paint does not carry the provider form or the
// coding console.
const AccountScreen = lazy(() => import("./screens/AccountScreen").then((m) => ({ default: m.AccountScreen })));
const AvatarStudioScreen = lazy(() => import("./screens/AvatarStudioScreen").then((m) => ({ default: m.AvatarStudioScreen })));
const ChannelsScreen = lazy(() => import("./screens/ChannelsScreen").then((m) => ({ default: m.ChannelsScreen })));
const CodingScreen = lazy(() => import("./screens/CodingScreen").then((m) => ({ default: m.CodingScreen })));
const ConnectionsScreen = lazy(() => import("./screens/ConnectionsScreen").then((m) => ({ default: m.ConnectionsScreen })));
const DevicesScreen = lazy(() => import("./screens/DevicesScreen").then((m) => ({ default: m.DevicesScreen })));
const GoalsScreen = lazy(() => import("./screens/GoalsScreen").then((m) => ({ default: m.GoalsScreen })));
const IdeasScreen = lazy(() => import("./screens/IdeasScreen").then((m) => ({ default: m.IdeasScreen })));
const LibraryScreen = lazy(() => import("./screens/LibraryScreen").then((m) => ({ default: m.LibraryScreen })));
const MemoryScreen = lazy(() => import("./screens/MemoryScreen").then((m) => ({ default: m.MemoryScreen })));
const Onboarding = lazy(() => import("./screens/Onboarding").then((m) => ({ default: m.Onboarding })));
const SettingsScreen = lazy(() => import("./screens/SettingsScreen").then((m) => ({ default: m.SettingsScreen })));
const SkillsScreen = lazy(() => import("./screens/SkillsScreen").then((m) => ({ default: m.SkillsScreen })));

function Loading() {
  return (
    <div className="flex h-full min-h-[40vh] items-center justify-center text-muted">
      <Loader2 className="animate-spin" size={20} />
    </div>
  );
}

/** The five glyphs: outlined at rest, filled with the button's own ink when selected. The fill is the state. */
const glyph = (active: boolean) => ({ size: 26, strokeWidth: active ? 2 : 1.7, fill: active ? "currentColor" : "none", fillOpacity: active ? 0.18 : 0 });
const TABS: Array<{ id: Tab; label: string; icon: (active: boolean) => ReactNode }> = [
  { id: "chat", label: "Chat", icon: (a) => <MessageCircle {...glyph(a)} /> },
  { id: "feed", label: "Feed", icon: (a) => <Newspaper {...glyph(a)} /> },
  { id: "ideas", label: "Ideas", icon: (a) => <Lightbulb {...glyph(a)} /> },
  { id: "goals", label: "Goals", icon: (a) => <SquareCheckBig {...glyph(a)} /> },
  { id: "library", label: "Library", icon: (a) => <LayoutGrid {...glyph(a)} /> },
];

export default function App() {
  const { state, setTab, openFile } = useStore();
  const account = state.hub?.account;
  const draftScope = JSON.stringify([state.authError, account?.base_url, account?.signed_in, account?.signed_in_at, account?.hint]);
  // Keep unsent text while moving between rooms, within this account and browser tab.
  const composerDrafts = useMemo(() => ({ scope: draftScope, texts: new Map<string, string>() }), [draftScope]);
  const firstSignIn = useFirstSignIn();
  const t = useT();

  // The document title follows the agent's name.
  useEffect(() => {
    const name = state.profile?.name?.trim();
    document.title = name && name.toLowerCase() !== "nanomuse" ? `${name} · nanoMuse` : "nanoMuse";
  }, [state.profile?.name]);

  // the desktop's quick-chat shortcut: to the chat, with the composer focused
  useEffect(() => {
    const off = desktopBridge()?.onQuickChat?.(() => {
      setTab("chat");
      requestAnimationFrame(() => window.dispatchEvent(new Event("nanomuse:quick-chat")));
    });
    return () => {
      if (typeof off === "function") off();
    };
  }, [setTab]);

  // `#devices` etc. opens a section straight away — the desktop tray menu links here.
  useEffect(() => {
    const jump = () => {
      const tab = window.location.hash.slice(1) as Tab;
      if (tab && TABS.some((x) => x.id === tab)) setTab(tab);
      else if (tab === "devices" || tab === "you" || tab === "memory" || tab === "connections" || tab === "channels" || tab === "skills" || tab === "account" || tab === "coding" || tab === "avatar") setTab(tab);
    };
    jump();
    window.addEventListener("hashchange", jump);
    return () => window.removeEventListener("hashchange", jump);
  }, [setTab]);

  // A freshly created account is owed two short steps (a password, which model
  // answers); they float over whatever comes next — setup or the chat.
  const firstSteps = firstSignIn && state.hub?.account.signed_in ? <FirstSignInSteps /> : null;

  // Lite (inside the showcase's phone): the runtime there is set up by its host, so the
  // first-run setup has nothing to ask; mark it done and go straight to the chat.
  const liteSetup = state.lite && state.settings !== null && !state.settings.onboarded;
  useEffect(() => {
    if (liteSetup) void api.onboarded(true).catch(() => undefined);
  }, [liteSetup]);

  if (state.authError) return <TokenGate />;
  // Nothing has arrived from the runtime yet: say so, instead of an empty chat.
  if (!state.loaded) return <Connecting error={state.error} />;
  // The account comes first when nothing else could answer: this runtime asks for one
  // (cloud.required), none is signed in, no model of one's own is ready, and the person has not
  // stepped past the door for a key of their own. The sign-in stays an invitation under Connections.
  if (signInDoorNeeded(state.hub, state.settings, state.signInSkipped)) {
    return <SignInGate />;
  }
  // First run: the server has not seen setup finish and nothing has been said yet.
  if (!state.lite && state.settings && !state.settings.onboarded && !state.onboardingDismissed && !state.threads.some((t) => t.events > 0)) {
    return (
      <Suspense fallback={<Loading />}>
        <Onboarding />
        {firstSteps}
      </Suspense>
    );
  }

  const pendingApprovals = state.pendingApprovals.length;
  // a plan change waiting for your answer is worth a red badge; the count of goals is not
  const proposals = state.goals.filter((g) => g.proposal && g.status !== "cancelled").length;
  const feedUnseen = state.pendingApprovals.filter((a) => a.ts > state.feedSeenAt).length;

  // One column on the phone; on a wide screen (a full browser) and in the desktop app at any
  // width, a sidebar takes over from the tab bar and the chats sheet — same screens either side.
  return (
    <div className={cx("mx-auto flex h-[100dvh] max-w-[760px] flex-col bg-bg sm:border-x sm:border-border", !state.lite && "wide:max-w-none wide:flex-row wide:border-x-0")}>
      {!state.lite && (
        <div className="hidden wide:block wide:h-full">
          <Sidebar />
        </div>
      )}
      <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
        {state.gone && (
          <div className="flex items-center justify-center gap-2 bg-surface-2 text-muted text-[12.5px] py-1">
            <WifiOff size={14} /> {t(state.lite ? "This demo has ended." : "This nanoMuse has stopped. Reload the page once it is running again.")}
          </div>
        )}
        {!state.gone && !state.connected && state.loaded && (
          <div className="flex items-center justify-center gap-2 bg-amber-500/15 text-amber-700 dark:text-amber-300 text-[12.5px] py-1">
            <WifiOff size={14} /> {t("Reconnecting to your nanoMuse…")}
          </div>
        )}
        {!state.lite && <DesktopRemoteHint />}
        {/* `tabbar-room` keeps the screens, the chat's composer included, above the floating bar;
            a wide window has the sidebar instead and gives the room back. */}
        <main className={cx("tabbar-room mx-auto min-h-0 w-full flex-1 wide:max-w-[900px]", !state.lite && "wide:pb-0")}>
          <Suspense fallback={<Loading />}>
            {state.tab === "chat" && <ChatScreen key={composerDrafts.scope} drafts={composerDrafts.texts} />}
            {state.tab === "feed" && <FeedScreen />}
            {state.tab === "ideas" && <IdeasScreen />}
            {state.tab === "goals" && <GoalsScreen />}
            {state.tab === "library" && <LibraryScreen />}
            {state.tab === "memory" && <MemoryScreen />}
            {state.tab === "skills" && <SkillsScreen />}
            {state.tab === "connections" && <ConnectionsScreen />}
            {state.tab === "channels" && <ChannelsScreen />}
            {state.tab === "devices" && <DevicesScreen />}
            {state.tab === "you" && <SettingsScreen />}
            {state.tab === "account" && <AccountScreen />}
            {state.tab === "coding" && <CodingScreen />}
            {state.tab === "avatar" && <AvatarStudioScreen />}
          </Suspense>
        </main>
        {/* Muse's bottom bar, as the Android app draws it: a floating frosted-glass pill, five glyphs,
            icons only. The pill sits 12px above the bottom edge, blurs what is behind it and carries
            a hairline edge; the current tab shows its filled glyph on an ink indicator (black in the
            light theme, white in the dark one, the glyph in the opposite colour), the others stay
            outlined in the muted grey. No labels: the fill and the indicator are the
            state. The pill is as wide as the chat's composer above it (the same 12px from the sides,
            `px-3` on the Composer's form), 420px at most and centred on a wider screen; the five
            slots share it equally and the indicator disc keeps its 60 by 46 inside the slot. In lite
            (the phone in the showcase) it shows whatever the width; otherwise a wide window has the
            sidebar instead. The nav itself lets taps through to the screen; only the pill takes them. */}
        <nav className={cx("tabbar-float pointer-events-none absolute inset-x-0 z-20 flex justify-center px-3", !state.lite && "wide:hidden")}>
          <ul className="pointer-events-auto flex w-full max-w-[420px] items-center gap-0.5 rounded-full bg-surface-2/55 px-3.5 py-1.5 ring-1 ring-border/50 backdrop-blur-2xl">
            {TABS.map((tab) => {
              const active = state.tab === tab.id;
              const badge = tab.id === "chat" ? pendingApprovals : tab.id === "feed" ? feedUnseen : tab.id === "goals" ? proposals : 0;
              return (
                <li key={tab.id} className="min-w-0 flex-1">
                  <button
                    type="button"
                    onClick={() => setTab(tab.id)}
                    aria-label={t(tab.label)}
                    aria-current={active ? "page" : undefined}
                    className={cx("flex h-[46px] w-full items-center justify-center", active ? "text-ink-fg" : "text-muted hover:text-fg")}
                  >
                    <span className={cx("relative flex h-[46px] w-full max-w-[60px] items-center justify-center rounded-full transition-colors duration-300", active && "bg-ink")}>
                      {tab.icon(active)}
                      {badge > 0 && (
                        <span className="absolute right-2.5 top-1 flex h-[17px] min-w-[17px] items-center justify-center rounded-full bg-rose-500 px-1 text-[10px] font-bold text-white">
                          {badge}
                        </span>
                      )}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>
      </div>
      <ChatsDrawer />
      <FileViewer path={state.viewer} onClose={() => openFile(null)} />
      {firstSteps}
      {state.toast && (
        <div className="pointer-events-none fixed inset-x-0 bottom-[calc(6rem+env(safe-area-inset-bottom))] z-[70] flex justify-center px-4">
          <div role="status" className="rise rounded-2xl bg-fg text-bg px-4 py-2 text-[13.5px] shadow-lg max-w-sm text-center">{state.toast}</div>
        </div>
      )}
    </div>
  );
}

/** The first seconds: the socket is on its way, or the runtime cannot be reached at all. */
function Connecting({ error }: { error: string | null }) {
  const t = useT();
  return (
    <div className="mx-auto flex h-[100dvh] max-w-sm flex-col items-center justify-center px-6 text-center">
      {/* the web's splash: the app's mark, no face (the face is the Muse, who is not here yet) */}
      <BrandMark size={72} />
      {error ? (
        <>
          <p className="mt-6 text-[15px] font-medium">{t("Could not reach your nanoMuse.")}</p>
          <p className="mt-1.5 text-[13px] text-muted">{t(error)}</p>
          <button type="button" onClick={() => window.location.reload()} className="mt-5 rounded-full bg-fg px-5 py-2 text-[14px] font-medium text-bg">
            {t("Try again")}
          </button>
        </>
      ) : (
        <p className="mt-6 flex items-center gap-2 text-[14px] text-muted">
          <Loader2 className="animate-spin" size={16} /> {t("Connecting to your nanoMuse…")}
        </p>
      )}
    </div>
  );
}

function TokenGate() {
  const [value, setValue] = useState("");
  const t = useT();
  return (
    <div className="mx-auto flex h-[100dvh] max-w-md flex-col items-center justify-center px-6 text-center">
      <BrandMark size={88} />
      <h1 className="mt-4 text-[22px] font-bold">{t("Connect to your nanoMuse")}</h1>
      <p className="mt-2 text-[14px] text-muted">
        {t("This app talks to the nanoMuse server you run yourself. Scan the QR code printed by")}{" "}
        <code className="rounded bg-surface-2 px-1">nanomuse serve</code>{t(", or paste the access token below.")}
      </p>
      <form
        className="mt-5 w-full flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (!value.trim()) return;
          setToken(value.trim());
          window.location.reload();
        }}
      >
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          aria-label={t("Access token")}
          placeholder={t("Access token")}
          className="flex-1 rounded-2xl bg-surface-2 px-4 py-2.5 text-[15px] outline-none focus:ring-2 focus:ring-accent/40"
        />
        <button type="submit" className="rounded-2xl bg-accent text-accent-fg px-4 font-medium">
          {t("Connect")}
        </button>
      </form>
    </div>
  );
}
