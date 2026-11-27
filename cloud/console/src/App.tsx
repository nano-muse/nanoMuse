/** The shell: the lock screen, the side navigation, the top bar (period, language, theme,
 *  who is operating), one page at a time, and the account and address drawers over it. */

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { actor as actorStore, ApiError, setLockedHandler, token } from "./lib/api";
import { clearCache, useData, useStored } from "./lib/hooks";
import { LANG_KEY, LangContext, initialLang, tableOf } from "./lib/i18n";
import type { Lang } from "./lib/locales";
import { GROUPS, useRoute, type Page } from "./lib/router";
import type { Health, Live } from "./lib/types";
import { AccountDrawer } from "./pages/AccountDrawer";
import { Abuse } from "./pages/Abuse";
import { Activity } from "./pages/Activity";
import { AddressDrawer } from "./pages/AddressDrawer";
import { Cohorts } from "./pages/Cohorts";
import { Controls } from "./pages/Controls";
import { Data } from "./pages/Data";
import { Demo } from "./pages/Demo";
import { Hands } from "./pages/Hands";
import { HealthPage } from "./pages/Health";
import { Invites } from "./pages/Invites";
import { LivePage } from "./pages/Live";
import { Models } from "./pages/Models";
import { Overview } from "./pages/Overview";
import { People } from "./pages/People";
import { Places } from "./pages/Places";
import { Platforms } from "./pages/Platforms";
import { Quality } from "./pages/Quality";
import { SettingsPage } from "./pages/Settings";
import { Site } from "./pages/Site";
import { StatsPage } from "./pages/Stats";
import { Turns } from "./pages/Turns";
import { Usage } from "./pages/Usage";
import { DialogHost, Seg, ToastHost, cx } from "./ui/primitives";
import { AdminLock } from "./ui/AdminLock";

export interface PageProps {
  days: number;
}

const PERIOD_PAGES = new Set<Page>(["overview", "usage", "platforms", "cohorts", "hands", "quality", "abuse", "places", "activity", "demo", "data", "turns", "site", "stats"]);
const DAY_OPTIONS: number[] = [7, 14, 30, 90, 365];

const PAGE_VIEWS: Record<Page, (p: PageProps) => ReactNode> = {
  overview: (p) => <Overview {...p} />,
  live: () => <LivePage />,
  usage: (p) => <Usage {...p} />,
  platforms: (p) => <Platforms {...p} />,
  cohorts: (p) => <Cohorts {...p} />,
  hands: (p) => <Hands {...p} />,
  quality: (p) => <Quality {...p} />,
  abuse: (p) => <Abuse {...p} />,
  people: () => <People />,
  invites: () => <Invites />,
  places: (p) => <Places {...p} />,
  activity: (p) => <Activity {...p} />,
  demo: (p) => <Demo {...p} />,
  data: (p) => <Data {...p} />,
  turns: (p) => <Turns {...p} />,
  health: () => <HealthPage />,
  site: (p) => <Site {...p} />,
  models: () => <Models />,
  stats: (p) => <StatsPage {...p} />,
  controls: () => <Controls />,
  settings: () => <SettingsPage />,
};

const ICONS: Record<string, string> = {
  overview: "M3 12h4l3-8 4 16 3-8h4",
  live: "M12 3v3m0 12v3M3 12h3m12 0h3M5.6 5.6l2.2 2.2m8.4 8.4 2.2 2.2M5.6 18.4l2.2-2.2m8.4-8.4 2.2-2.2",
  usage: "M4 20V10m6 10V4m6 16v-7m4 7H2",
  platforms: "M4 5h16v11H4zM8 20h8M12 16v4",
  cohorts: "M4 4v16h16M8 14l4-4 3 3 5-6",
  hands: "M7 3h10v18H7zM11 18h2",
  quality: "M12 3l2.5 6 6.5.6-5 4.3 1.6 6.4L12 17l-5.6 3.3L8 13.9 3 9.6 9.5 9z",
  abuse: "M12 3 2 21h20zM12 10v5m0 3v.5",
  people: "M16 19v-1a4 4 0 0 0-8 0v1M12 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM20 19v-1a3 3 0 0 0-2-2.8M4 19v-1a3 3 0 0 1 2-2.8",
  invites: "M4 8l8 5 8-5M4 8v10h16V8M4 8l8-4 8 4",
  places: "M12 21s-7-6.5-7-11a7 7 0 1 1 14 0c0 4.5-7 11-7 11zM12 12a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
  activity: "M3 12h4l3 7 4-14 3 7h4",
  demo: "M4 5h16v12H4zM9 21h6M12 17v4",
  data: "M4 6c0-1.5 3.6-3 8-3s8 1.5 8 3-3.6 3-8 3-8-1.5-8-3zm0 0v12c0 1.5 3.6 3 8 3s8-1.5 8-3V6M4 12c0 1.5 3.6 3 8 3s8-1.5 8-3",
  turns: "M5 4h14v10H9l-4 4zM8 8h8M8 11h5",
  health: "M20 12h-3l-2 6-4-12-2 6H4",
  site: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18",
  models: "M4 7h16M4 12h16M4 17h10",
  stats: "M4 19h16M6 16V9m4 7V5m4 11v-4m4 4V8",
  controls: "M4 7h10m4 0h2M4 17h4m4 0h8M14 5v4M8 15v4",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19 12a7 7 0 0 0-.1-1l2-1.5-2-3.5-2.4 1a7 7 0 0 0-1.7-1L14.5 3h-5l-.3 2.6a7 7 0 0 0-1.7 1l-2.4-1-2 3.5 2 1.5a7 7 0 0 0 0 2l-2 1.5 2 3.5 2.4-1a7 7 0 0 0 1.7 1l.3 2.6h5l.3-2.6a7 7 0 0 0 1.7-1l2.4 1 2-3.5-2-1.5c.1-.3.1-.7.1-1z",
};

function Icon({ d, className }: { d: string; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={cx("h-[17px] w-[17px] flex-none", className)} fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
      <path d={d} />
    </svg>
  );
}

export default function App() {
  const [lang, setLangState] = useState<Lang>(initialLang);
  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    localStorage.setItem(LANG_KEY, l);
    document.documentElement.lang = l === "zh" ? "zh-CN" : "en";
  }, []);
  const [dark, setDark] = useStored("nm.admin.dark", window.matchMedia("(prefers-color-scheme: dark)").matches);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);
  const [days, setDays] = useStored<number>("nm.admin.days", 30);
  const [unlocked, setUnlocked] = useState(() => !!token.get());
  const [expired, setExpired] = useState(false);
  const [actorName, setActorName] = useState(actorStore.get());
  useEffect(() => {
    setLockedHandler(() => {
      clearCache();
      setExpired(true);
      setUnlocked(false);
    });
  }, []);
  const route = useRoute();
  const T = tableOf(lang);
  const ctx = useMemo(() => ({ lang, setLang }), [lang, setLang]);

  const health = useData<Health>(unlocked ? "/v1/admin/health" : null, { poll: 60_000, maxAge: 30_000 });
  const live = useData<Live>(unlocked && route.page !== "live" ? "/v1/admin/live" : null, { poll: 15_000, maxAge: 10_000 });
  const badges: Partial<Record<Page, { n: number; tone: "bad" | "warn" | "" }>> = {};
  if (health.data && !health.data.ok) badges.health = { n: health.data.problems.length, tone: "bad" };
  if (live.data && live.data.gate.waiting > 0) badges.live = { n: live.data.gate.waiting, tone: "warn" };
  else if (live.data && live.data.gate.active > 0) badges.live = { n: live.data.gate.active, tone: "" };

  useEffect(() => {
    document.title = unlocked ? `${T.nav[route.page]} · nanoMuse admin` : "nanoMuse · admin";
  }, [route.page, T, unlocked]);

  if (!unlocked) {
    return (
      <LangContext.Provider value={ctx}>
        <AdminLock
          expired={expired}
          onEnter={() => {
            setExpired(false);
            setUnlocked(true);
          }}
        />
      </LangContext.Provider>
    );
  }

  const acct = route.params.get("acct");
  const ip = route.params.get("ip");
  const version = health.data?.version || "";

  return (
    <LangContext.Provider value={ctx}>
      <ToastHost>
        <DialogHost>
          <div className="flex min-h-full">
            <nav className="sticky top-0 hidden h-screen w-[196px] flex-none flex-col gap-0.5 overflow-y-auto border-r border-line bg-panel px-2.5 py-3 md:flex">
              <a href="#overview" className="mb-3 flex items-center gap-2 px-2 py-1">
                <img src="/app/icon.svg" alt="" className="h-6 w-6 rounded-md" />
                <span className="text-[14px] font-semibold tracking-tight">{T.app}</span>
              </a>
              {GROUPS.map((g) => (
                <div key={g.id} className="mb-2">
                  <div className="px-2.5 pb-1 text-[11px] font-medium tracking-wide text-ink-3 uppercase">{T.nav[g.id]}</div>
                  {g.pages.map((p) => {
                    const b = badges[p];
                    return (
                      <a key={p} href={`#${p}`} className={cx("flex items-center gap-2.5 rounded-lg px-2.5 py-[7px] text-[13px] text-ink-2 hover:bg-panel-2 hover:text-ink", route.page === p && "bg-accent-soft font-medium text-accent hover:bg-accent-soft hover:text-accent")}>
                        <Icon d={ICONS[p]} />
                        <span className="truncate">{T.nav[p]}</span>
                        {b && <span className={cx("ml-auto pill", b.tone, p === "live" && b.tone === "" && "pulse")}>{b.n}</span>}
                      </a>
                    );
                  })}
                </div>
              ))}
              <div className="mt-auto px-2.5 pt-2 text-[11px] text-ink-3">{version && T.se.version(version)}</div>
            </nav>
            <div className="flex min-w-0 flex-1 flex-col">
              <header className="sticky top-0 z-30 flex flex-wrap items-center gap-2 border-b border-line bg-bg/85 px-4 py-2 backdrop-blur md:px-6">
                <select className="inp md:hidden" value={route.page} onChange={(e) => route.go(e.target.value as Page)}>
                  {GROUPS.flatMap((g) => g.pages).map((p) => (
                    <option key={p} value={p}>
                      {T.nav[p]}
                    </option>
                  ))}
                </select>
                <h1 className="m-0 hidden text-[16px] font-semibold tracking-tight md:block">{T.nav[route.page]}</h1>
                <div className="ml-auto flex flex-wrap items-center gap-2">
                  {PERIOD_PAGES.has(route.page) && <Seg options={DAY_OPTIONS.map((d) => ({ id: String(d), label: T.top.days(d) }))} value={String(DAY_OPTIONS.includes(days) ? days : 30)} onChange={(v) => setDays(Number(v))} />}
                  <input className="inp w-28" placeholder={T.top.actor} title={T.top.actorHint} value={actorName} onChange={(e) => setActorName(e.target.value)} onBlur={() => actorStore.set(actorName)} />
                  <button type="button" className="btn sm" onClick={() => setLang(lang === "zh" ? "en" : "zh")}>
                    {T.top.lang}
                  </button>
                  <button type="button" className="btn sm" title={T.top.theme} onClick={() => setDark(!dark)}>
                    {dark ? "☾" : "☀"}
                  </button>
                </div>
              </header>
              <main className="mx-auto w-full max-w-[1560px] flex-1 px-4 py-4 md:px-6">
                <div key={route.page} className="fade-in flex flex-col gap-3">
                  {PAGE_VIEWS[route.page]({ days })}
                </div>
              </main>
            </div>
          </div>
          {acct && <AccountDrawer id={acct} days={days} onClose={() => route.set({ acct: null })} />}
          {ip && <AddressDrawer ip={ip} onClose={() => route.set({ ip: null })} />}
        </DialogHost>
      </ToastHost>
    </LangContext.Provider>
  );
}

export const errorText = (e: ApiError | null): string => (e ? (e.code === "offline" ? "offline" : `${e.status || ""} ${e.code}: ${e.message}`.trim()) : "");
