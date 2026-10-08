import { Star } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useLocale, useT } from "../i18n";
import {
  askDue,
  askId,
  DEFAULT_POLICY,
  type KV,
  migrateLedger,
  type NudgesPolicy,
  normalizePolicy,
  readLedger,
  recordAsk,
  recordDay,
  recordStarred,
  recordTask,
  type StarMoment,
  starSentence,
} from "../nudges";
import type { CloudConfig } from "../types";
import { cx } from "../util";
import { REPO_URL } from "./CommunityNotice";
import { primaryBtn, secondaryBtn } from "./Form";

export type { StarMoment } from "../nudges";

/**
 * The ask for a star, at the moments it is fair to make it — and the relay says which
 * (contract C1, `GET /api/nudges`): the account page the first time it is seen signed in,
 * after the 3rd, 10th and 30th task, after a face is drawn, when the allowance is used up,
 * on the 7th and 30th day the app was opened, when a goal is marked done. A cooldown between
 * asks and a lifetime cap, both from the policy; going to GitHub from any of them ends them
 * all. A card where the moment is, never a dialog — and the tone is a thank you, not a bill.
 */

// ----------------------------------------------------------------------------- the ledger (localStorage)
const memory = new Map<string, string>();
/** localStorage, or a page-lifetime map where it is not allowed (private mode): the ask may come back; it is still only a card. */
const kv: KV = {
  getItem: (k) => {
    try {
      return localStorage.getItem(k);
    } catch {
      return memory.get(k) ?? null;
    }
  },
  setItem: (k, v) => {
    try {
      localStorage.setItem(k, v);
    } catch {
      memory.set(k, v);
    }
  },
  removeItem: (k) => {
    try {
      localStorage.removeItem(k);
    } catch {
      memory.delete(k);
    }
  },
};
let migrated = false;
function ledger() {
  if (!migrated) {
    migrated = true;
    return migrateLedger(kv);
  }
  return readLedger(kv);
}

// ----------------------------------------------------------------------------- the policy (the relay's, through the runtime)
let policy: NudgesPolicy = DEFAULT_POLICY;
let policyReady = false;
let policyPending: Promise<void> | null = null;
const listeners = new Set<() => void>();

/** Read once per page load (the runtime itself asks the relay at most once a day). */
function loadPolicy(): Promise<void> {
  policyPending ??= api
    .nudges()
    .then((v) => {
      policy = normalizePolicy(v?.policy);
    })
    .catch(() => {
      policy = DEFAULT_POLICY;
    })
    .finally(() => {
      policyReady = true;
      listeners.forEach((fn) => fn());
    });
  return policyPending;
}

/** The policy in force, and whether it has been read yet (until then, no ask is drawn). */
export function useStarPolicy(): { policy: NudgesPolicy; ready: boolean } {
  const [, tick] = useState(0);
  useEffect(() => {
    const fn = () => tick((n) => n + 1);
    listeners.add(fn);
    void loadPolicy();
    return () => {
      listeners.delete(fn);
    };
  }, []);
  return { policy, ready: policyReady };
}

// ----------------------------------------------------------------------------- the moments
/** One more task finished in this browser; the count so far. */
export const countTask = (): number => recordTask(kv);
/** The app was opened today (first time today → `fresh`); the count of days so far. */
export const countDay = (): { days: number; fresh: boolean } => recordDay(kv, new Date());

/** Still worth asking at this moment (`n`: the task or day count just reached). */
export const starDue = (m: StarMoment, n?: number): boolean => policyReady && askDue(m, policy, ledger(), Date.now(), n);
/** The card was shown (or waved away): one ask, the cooldown starts. */
export const starShown = (m: StarMoment, n?: number): void => {
  recordAsk(kv, askId(m, n), Date.now());
};
/** The person has been to GitHub from one of the asks, or said they already starred. */
export const starred = (): boolean => ledger().starred;

/**
 * The star is done: the person went to GitHub from any "Star on GitHub" or said "I already
 * starred". No ask comes back in this browser, whatever the cooldown and the asks left.
 */
export const markStarred = (): void => recordStarred(kv);

/** Off to GitHub, and no more asking anywhere. */
export function openStar(repoUrl?: string): void {
  markStarred();
  window.open(repoUrl || policy.star.url || REPO_URL, "_blank", "noopener,noreferrer");
}

/** The words for each moment (one source, so every client says the same thing). */
export function starText(t: (s: string, vars?: Record<string, string | number>) => string, m: StarMoment, n?: number): string {
  switch (m) {
    case "signed_in":
      return t(
        "Welcome. nanoMuse is free, open source and non-profit, a personal agent for anyone who runs it. If that is worth something to you, a star on GitHub is how the next person finds it.",
      );
    case "tasks":
      return n === 3
        ? t("Three tasks done. If nanoMuse is useful, a star on GitHub helps the next person find it.")
        : n === 10
          ? t("Ten tasks together. If nanoMuse has become part of your day, a star on GitHub tells others it is worth a try.")
          : t("{n} tasks done. If nanoMuse is useful, a star on GitHub helps the next person find it.", { n: n ?? 0 });
    case "new_look":
      return t("A new face, drawn for you. If you like where nanoMuse is going, a star on GitHub helps more people find it.");
    case "exhausted":
      return t("The free allowance is used up. Thank you for coming this far. If nanoMuse has earned it, a star on GitHub keeps the project in view for the next person.");
    case "days_used":
      return n === 7
        ? t("A week with nanoMuse. If it has earned a place in your day, a star on GitHub helps the next person find it.")
        : n === 30
          ? t("A month with nanoMuse. If it has become part of your routine, a star on GitHub tells others it is worth a try.")
          : t("{n} days with nanoMuse. If it has earned a place in your day, a star on GitHub helps the next person find it.", { n: n ?? 0 });
    case "goal_done":
      return t("Goal reached. If nanoMuse helped you get there, a star on GitHub tells the people building it that it did.");
  }
}

/**
 * The relay's public figures (relay 0.15, `/api/cloud/config`): the allowance a new account
 * gets, the invite bonus, the repository — read once per page load and shared, so the copy
 * prints what the relay's operator set today rather than a number baked into the build.
 * Empty until it answers, and from an older relay; callers keep their fallbacks.
 */
let cached: CloudConfig | null = null;
let pending: Promise<CloudConfig> | null = null;
export function useCloudConfig(): CloudConfig {
  const [cfg, setCfg] = useState<CloudConfig>(cached ?? {});
  useEffect(() => {
    if (cached) return;
    pending ??= api
      .cloudConfig()
      .then((c) => (cached = c && typeof c === "object" ? c : {}))
      .catch(() => (cached = {}));
    let live = true;
    pending.then((c) => live && setCfg(c));
    return () => {
      live = false;
    };
  }, []);
  return cfg;
}

/** The star card's sentence: the relay's when it set one for this UI's language, else `own`. */
export function useStarSentence(own: string): string {
  const { policy: current } = useStarPolicy();
  return starSentence(current, useLocale() === "zh-CN", own);
}

/**
 * One card: the star, a line saying why, "Star on GitHub", "Not now" and "I already starred". The line is the
 * relay's sentence when its policy carries one (`star.text`, `star.text_zh` for a Chinese
 * UI), else `text`, the app's own words for the moment; the title and buttons stay the app's.
 */
export function StarNudge({ text, onDone, className }: { text: string; onDone: () => void; className?: string }) {
  const t = useT();
  const cfg = useCloudConfig();
  const body = useStarSentence(text);
  return (
    <section className={cx("rounded-[22px] border border-amber-400/40 bg-amber-50/70 p-4 dark:bg-amber-400/[0.08]", className)}>
      <div className="flex items-start gap-2.5">
        <Star size={18} className="mt-0.5 shrink-0 text-amber-500" />
        <div className="min-w-0 flex-1">
          <div className="text-[14px] font-semibold leading-snug">{t("A star on GitHub helps")}</div>
          <p className="mt-1 text-[13px] leading-relaxed text-fg/85">{body}</p>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2 pl-7">
        <button
          type="button"
          className={cx(primaryBtn, "!w-auto !py-1.5 !px-3.5 text-[13px]")}
          onClick={() => {
            openStar(cfg.repo_url);
            onDone();
          }}
        >
          {t("Star on GitHub")}
        </button>
        <button type="button" className={cx(secondaryBtn, "!w-auto !py-1.5 !px-3.5 text-[13px]")} onClick={onDone}>
          {t("Not now")}
        </button>
        <button
          type="button"
          className={cx(secondaryBtn, "!w-auto !py-1.5 !px-3.5 text-[13px]")}
          onClick={() => {
            markStarred();
            onDone();
          }}
        >
          {t("I already starred")}
        </button>
      </div>
    </section>
  );
}

/**
 * The card for a moment, shown once: `due` says the moment has come (the account was just
 * seen signed in; a task just finished; a goal was marked done), `n` the count reached for
 * `tasks` / `days_used`. Waits for the policy, then marks the ask as made as soon as the
 * card is drawn.
 */
export function StarNudgeOnce({ moment, n, text, className, due = true }: { moment: StarMoment; n?: number; text?: string; className?: string; due?: boolean }) {
  const t = useT();
  const [open, setOpen] = useStarAsk(moment, due, n);
  if (!open) return null;
  return <StarNudge text={text ?? starText(t, moment, n)} onDone={() => setOpen(false)} className={className} />;
}

/**
 * The gate as a hook, for a place that draws its own row (the allowance "ways" card): once
 * the policy is read and the moment is due, `open` turns true and the ask is recorded; the
 * setter closes it.
 */
export function useStarAsk(moment: StarMoment, due = true, n?: number): [boolean, (open: boolean) => void] {
  const { ready } = useStarPolicy();
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!due || !ready || open || !starDue(moment, n)) return;
    starShown(moment, n);
    setOpen(true);
  }, [due, ready, moment, n, open]);
  return [open, setOpen];
}
