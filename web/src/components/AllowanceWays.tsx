import { ChevronDown, ChevronUp, Copy, ExternalLink, KeyRound, LogIn, Share2, Sparkles, Star, Users, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api";
import { getLocale, useT } from "../i18n";
import { useStore } from "../store";
import { coversLine, OWN_KEY_DOCS_URL, plans, presetFor, providerName, providersFor, regionOf } from "../providers";
import { ownKeyLine, ownKeyWay } from "../region";
import type { Guidance } from "../types";
import { cx } from "../util";
import { ChatGptSignIn } from "./ChatGptSignIn";
import { primaryBtn, secondaryBtn } from "./Form";
import { markStarred, openStar, starText, useCloudConfig, useStarAsk, useStarSentence } from "./StarNudge";

/**
 * What the relay says beside a `429 allowance_exhausted` (and what `/v1/me.spend` carries):
 * the numbers and where the ways on lead. Every field is optional so a card can be
 * drawn from an older relay's reply too; `guidance` (relay 0.21) carries the relay's own
 * list of providers for the region, used when present, else the bundled catalogue.
 */
export interface AllowanceInfo {
  left?: number | null;
  grant?: number;
  invite_url?: string;
  /** what an invitation adds to the inviter's pool — and (relay 0.9) to the friend's */
  invite_bonus_cny?: number;
  invitee_bonus_cny?: number;
  own_key_docs?: string;
  guidance?: Guidance;
}

export const OWN_KEY_DOCS = OWN_KEY_DOCS_URL;
/** The preset the Connections page opens with when someone comes here for their own key. */
const PRESET_HINT = "nm.connections.preset";

/**
 * Send the person to Connections with the region's own-key provider preselected (contract
 * C5): Alibaba Cloud Bailian on the mainland, OpenRouter elsewhere.
 */
export function openOwnKeySetup(setTab: (tab: "connections") => void, preset: string = ownKeyWay().preset): void {
  try {
    sessionStorage.setItem(PRESET_HINT, preset);
  } catch {
    /* private mode: the page still opens, on the current preset */
  }
  setTab("connections");
}

/** The preset a card asked Connections to open with, once. */
export function takePresetHint(): string | null {
  try {
    const v = sessionStorage.getItem(PRESET_HINT);
    if (v) sessionStorage.removeItem(PRESET_HINT);
    return v;
  } catch {
    return null;
  }
}

/**
 * The ways on when the free allowance is (nearly) spent (contracts C5 and C11): one's own
 * model key (Alibaba Cloud Bailian first on the mainland — free quota for new accounts,
 * one key for chat, the hands, pictures and clips; OpenRouter first elsewhere, since
 * Bailian only signs up mainland accounts; the rest of the catalogue folded under "more",
 * each with what its key covers), a plan one already pays for (ChatGPT here, through the
 * runtime; Claude and Kimi on the phones), and inviting a friend (the bonus goes to
 * both). Sign-in and the devices keep working whichever is chosen: the allowance only
 * gates the model.
 */
export function AllowanceWays({
  info,
  exhausted,
  compact,
}: {
  info: AllowanceInfo;
  /** true = the pool is spent (the card leads with that); false = the 80 % heads-up */
  exhausted: boolean;
  /** inside the chat: tighter spacing, no big title */
  compact?: boolean;
  /** kept for the callers of 0.5 (nothing on the card changes the account any more) */
  onChanged?: () => void;
}) {
  const t = useT();
  const { toast, setTab, state } = useStore();
  const account = state.hub?.account;
  const way = ownKeyWay(account);
  const region = regionOf(account);
  const locale = getLocale();
  const inviteBonus = info.invite_bonus_cny ?? 5;
  const docs = info.own_key_docs || info.guidance?.docs || OWN_KEY_DOCS;
  const link = info.invite_url || "";
  const [more, setMore] = useState(false);
  const [signIn, setSignIn] = useState(false);
  // the other providers with a key: the relay's list for the region when it sent one, else the catalogue's
  const others = (info.guidance?.providers ?? providersFor(region)).filter((p) => p.id !== way.id).map((p) => ({
    id: p.id,
    name: providerName(p, locale),
    keyUrl: p.key_url,
    covers: "covers" in p ? p.covers : p.capabilities,
  }));
  const planNames = plans().map((p) => p.name);

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast(t("Copied"));
    } catch {
      toast(text);
    }
  };
  const share = async () => {
    const text = t("Try nanoMuse with me, a fully open-source personal agent, free to use. Sign up with my link: {link}", { link });
    const nav = navigator as Navigator & { share?: (data: { text: string }) => Promise<void> };
    if (nav.share) {
      try {
        await nav.share({ text });
        return;
      } catch {
        /* cancelled — fall through to the clipboard */
      }
    }
    await copy(text);
  };
  const cfg = useCloudConfig();
  // the ask for a star among the ways on — when the policy allows it (contract C1)
  const [starAsk, setStarAsk] = useStarAsk("exhausted", exhausted);
  const starLine = useStarSentence(starText(t, "exhausted"));
  const lead = exhausted
    ? t("The free allowance is used up.")
    : t("Nearly used up: ¥{left} of ¥{grant} left.", { left: (info.left ?? 0).toFixed(2), grant: (info.grant ?? 0).toFixed(0) });

  return (
    <div className={cx("space-y-2.5", !compact && "pt-1")}>
      <div>
        <div className={cx("font-semibold", compact ? "text-[13.5px]" : "text-[15px]")}>{lead}</div>
        <div className="mt-0.5 text-[12.5px] text-muted">{t("Three ways on; your sign-in and your devices keep working whichever you pick.")}</div>
      </div>

      <Way icon={<KeyRound size={16} />} tone="bg-accent/12 text-accent" title={t("Use your own model key")}>
        <p className="text-[12.5px] text-muted">{ownKeyLine(t, account)}</p>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => openOwnKeySetup(setTab, way.preset)} className={cx(primaryBtn, "inline-flex items-center gap-1.5 py-2")}>
            <KeyRound size={14} /> {t("Set it up")}
          </button>
          <a href={way.keyUrl} target="_blank" rel="noopener noreferrer" className={cx(secondaryBtn, "inline-flex items-center gap-1.5")}>
            <ExternalLink size={14} /> {t("Get a key from {vendor}", { vendor: way.label })}
          </a>
          <a href={docs} target="_blank" rel="noopener noreferrer" className={cx(secondaryBtn, "inline-flex items-center gap-1.5")}>
            <ExternalLink size={14} /> {t("Step-by-step guide")}
          </a>
        </div>
        {others.length > 0 && (
          <div>
            <button type="button" onClick={() => setMore(!more)} className="inline-flex items-center gap-1 text-[12px] text-muted">
              {more ? <ChevronUp size={13} /> : <ChevronDown size={13} />} {t("Other providers and what each key covers")}
            </button>
            {more && (
              <ul className="mt-1.5 space-y-1 text-[12.5px]">
                {others.map((p) => (
                  <li key={p.id} className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <span>
                      <span className="font-medium">{p.name}</span> <span className="text-muted">· {coversLine(t, p.covers)}</span>
                    </span>
                    <span className="flex gap-2">
                      <button type="button" onClick={() => openOwnKeySetup(setTab, presetFor(p.id))} className="text-accent">
                        {t("Set it up")}
                      </button>
                      <a href={p.keyUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 text-accent">
                        {t("Get a key")} <ExternalLink size={11} />
                      </a>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </Way>

      <Way icon={<LogIn size={16} />} tone="bg-emerald-500/12 text-emerald-600 dark:text-emerald-300" title={t("Sign in with a plan you already pay for")}>
        <p className="text-[12.5px] text-muted">
          {t("{plans}: the plan's models answer here, no key to make. ChatGPT works on every device, the others on the phones. A ChatGPT sign-in covers chat and the hands; pictures and clips still want a key.", { plans: planNames.join(t(", ")) })}
        </p>
        {signIn ? (
          <ChatGptSignIn compact onChanged={() => setSignIn(false)} />
        ) : (
          <button type="button" onClick={() => setSignIn(true)} className={cx(secondaryBtn, "inline-flex items-center gap-1.5")}>
            <LogIn size={14} /> {t("Sign in with ChatGPT")}
          </button>
        )}
      </Way>

      <Way icon={<Users size={16} />} tone="bg-violet-500/12 text-violet-600 dark:text-violet-300" title={t("Invite a friend: +¥{bonus} for you and +¥{bonus} for them, for each new person who signs up with your link.", { bonus: inviteBonus.toFixed(0) })}>
        {link ? (
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => void share()} className={cx(secondaryBtn, "inline-flex items-center gap-1.5")}>
              <Share2 size={14} /> {t("Share the link")}
            </button>
            <button type="button" onClick={() => void copy(link)} className={cx(secondaryBtn, "inline-flex items-center gap-1.5")}>
              <Copy size={14} /> {t("Copy the link")}
            </button>
          </div>
        ) : (
          <button type="button" onClick={() => setTab("account")} className={cx(secondaryBtn, "inline-flex items-center gap-1.5")}>
            <Share2 size={14} /> {t("Your invite link is under Account")}
          </button>
        )}
      </Way>

      {exhausted && starAsk && (
        <Way icon={<Star size={16} />} tone="bg-amber-400/15 text-amber-600 dark:text-amber-300" title={starLine}>
          <button type="button" onClick={() => openStar(cfg.repo_url)} className={cx(secondaryBtn, "inline-flex items-center gap-1.5")}>
            <Star size={14} /> {t("Star on GitHub")}
          </button>
          <button
            type="button"
            onClick={() => {
              markStarred();
              setStarAsk(false);
            }}
            className={cx(secondaryBtn, "inline-flex items-center gap-1.5")}
          >
            {t("I already starred")}
          </button>
        </Way>
      )}
    </div>
  );
}

function Way({ icon, tone, title, children }: { icon: ReactNode; tone: string; title: string; children: ReactNode }) {
  return (
    <div className="flex gap-3 rounded-2xl bg-surface-2/60 p-3">
      <span className={cx("flex h-8 w-8 shrink-0 items-center justify-center rounded-xl", tone)}>{icon}</span>
      <div className="min-w-0 flex-1 space-y-2">
        <div className="text-[13px] font-medium leading-snug">{title}</div>
        {children}
      </div>
    </div>
  );
}

/** The pool size the heads-up was last shown for: the strip comes back only once the pool has grown. */
const WARNED_KEY = "nm.cloud.warned_grant";

/**
 * The 80 % heads-up, once: after a turn finishes on the account's model, ask the runtime for
 * the account and, when the relay says `warn` (under ¥2 of the pool left) and the strip has
 * not been shown for this pool size yet, show one dismissible line above the composer that
 * leads to the account page. Never a modal; nothing while the pool is spent (the card in the
 * chat says that) or without limit.
 */
export function AllowanceHeadsUp() {
  const t = useT();
  const { state, setTab } = useStore();
  const [info, setInfo] = useState<AllowanceInfo | null>(null);
  const lastCheck = useRef(0);
  const account = state.hub?.account;
  const eligible = !!account?.signed_in && !!account.is_model;
  const finishedAt = state.finishedAt;

  useEffect(() => {
    if (!eligible || !finishedAt || info) return;
    if (Date.now() - lastCheck.current < 60_000) return;
    lastCheck.current = Date.now();
    let cancelled = false;
    api
      .cloudMe()
      .then((me) => {
        if (cancelled) return;
        const s = me.spend;
        const grant = s.grant ?? s.allowance_cny ?? 0;
        const left = s.left ?? null;
        if (s.unlimited || !s.warn || left === null || left <= 0) return;
        let warnedFor: string | null = null;
        try {
          warnedFor = localStorage.getItem(WARNED_KEY);
        } catch {
          /* private mode: show it; it will show again next load */
        }
        if (warnedFor === String(grant)) return;
        setInfo({
          left,
          grant,
          invite_url: me.invite?.url,
          invite_bonus_cny: s.invite_bonus_cny,
          invitee_bonus_cny: s.invitee_bonus_cny,
          own_key_docs: s.own_key_docs,
          guidance: s.guidance,
        });
      })
      .catch(() => {
        /* offline or signed out meanwhile: no strip */
      });
    return () => {
      cancelled = true;
    };
  }, [eligible, finishedAt, info]);

  if (!info) return null;
  const dismiss = () => {
    try {
      localStorage.setItem(WARNED_KEY, String(info.grant ?? 0));
    } catch {
      /* ignore */
    }
    setInfo(null);
  };
  return (
    <div className="rise mx-3 mb-1.5 flex items-start gap-2 rounded-2xl bg-amber-500/12 px-3 py-2 text-[12.5px] leading-snug text-amber-800 dark:text-amber-200">
      <Sparkles size={14} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1">
        {t("Nearly used up: ¥{left} of ¥{grant} left.", { left: (info.left ?? 0).toFixed(2), grant: (info.grant ?? 0).toFixed(0) })}{" "}
        {t("Invite a friend (+¥{invite} for each of you) or bring your own key; your sign-in keeps working either way.", {
          invite: (info.invite_bonus_cny ?? 5).toFixed(0),
        })}{" "}
        <button
          type="button"
          onClick={() => {
            dismiss();
            setTab("account");
          }}
          className="font-semibold underline decoration-dotted underline-offset-2"
        >
          {t("See the ways")}
        </button>
      </div>
      <button type="button" onClick={dismiss} aria-label={t("Dismiss")} className="shrink-0 rounded-full p-0.5 opacity-70 hover:opacity-100">
        <X size={14} />
      </button>
    </div>
  );
}
