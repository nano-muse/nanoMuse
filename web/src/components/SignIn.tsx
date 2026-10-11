import { KeyRound, Loader2, MessageSquareText } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { api } from "../api";
import { useT } from "../i18n";
import { isMainland, looksLikeForeignNumber } from "../region";
import { cx } from "../util";
import { markFirstSignIn } from "./FirstSignInSteps";
import { inputCls, primaryBtn, secondaryBtn } from "./Form";
import { useCloudConfig } from "./StarNudge";

/**
 * Signing in to nanoMuse Cloud: a code sent to a mainland phone number (SMS) or an e-mail
 * address, or — once one is set — the account password. The same form everywhere it is needed (first run, the gate, the
 * account screen); the key lands in the vault on the machine running nanoMuse.
 *
 * A friend's invite code (``?invite=CODE`` on the page URL, remembered until used, or typed
 * into the optional field) travels with the code sign-in; it counts for a new account only.
 */
const INVITE_KEY = "nm.invite";

/** The invite code from the page URL (kept for later) or from an earlier visit. */
export function pendingInvite(): string {
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("invite");
    if (fromUrl) {
      const clean = normalizeInvite(fromUrl);
      if (clean) localStorage.setItem(INVITE_KEY, clean);
    }
    return localStorage.getItem(INVITE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function normalizeInvite(v: string): string {
  return v
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, "")
    .slice(0, 8);
}
/** The keyboard for the identifier box: digits for a number, the e-mail layout otherwise. */
export function identifierInputMode(value: string): "tel" | "email" {
  return /^\s*[+\d]/.test(value) ? "tel" : "email";
}

export function SignIn({
  onSignedIn,
  /** after signing in, make the relay the model provider as well */
  useAsModel = false,
  /** the button label for the final step */
  cta,
  autoFocus = true,
}: {
  onSignedIn: () => void | Promise<void>;
  useAsModel?: boolean;
  cta?: string;
  autoFocus?: boolean;
}) {
  const t = useT();
  const ids = useId();
  const cfg = useCloudConfig();
  const [mode, setMode] = useState<"code" | "password">("code");
  const [identifier, setIdentifier] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState<"code" | "verify" | "login" | "model" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [invite, setInvite] = useState("");
  const [inviteOpen, setInviteOpen] = useState(false);
  useEffect(() => {
    const code = pendingInvite();
    if (code) {
      setInvite(code);
      setInviteOpen(true);
    }
  }, []);

  const finish = async () => {
    if (useAsModel) {
      setBusy("model");
      try {
        await api.cloudUseAsModel();
      } catch {
        /* the account is in; the model can be picked in Connections */
      }
    }
    await onSignedIn();
  };

  const sendCode = async () => {
    const id = identifier.trim();
    if (!id) return;
    setBusy("code");
    setError(null);
    try {
      await api.cloudCode(id);
      setSent(true);
    } catch (e) {
      setError(t((e as Error).message));
    } finally {
      setBusy(null);
    }
  };

  const verify = async () => {
    const id = identifier.trim();
    if (!id || code.trim().length < 4) return;
    setBusy("verify");
    setError(null);
    try {
      const r = await api.cloudVerify(id, code.trim(), invite.trim());
      // a brand-new account is owed two short steps (password, model source) — see FirstSignInSteps
      if (r.created) markFirstSignIn();
      setCode("");
      setSent(false);
      try {
        localStorage.removeItem(INVITE_KEY);
      } catch {
        /* storage may be off */
      }
      await finish();
    } catch (e) {
      setError(t((e as Error).message));
    } finally {
      setBusy(null);
    }
  };

  const login = async () => {
    const id = identifier.trim();
    if (!id || !password) return;
    setBusy("login");
    setError(null);
    try {
      await api.cloudLogin(id, password);
      setPassword("");
      await finish();
    } catch (e) {
      setError(t((e as Error).message));
    } finally {
      setBusy(null);
    }
  };

  const submit = () => void (mode === "password" ? login() : sent ? verify() : sendCode());
  const label = cta ?? (useAsModel ? t("Sign in and use its model") : t("Sign in"));

  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <div className="grid grid-cols-2 gap-1 rounded-2xl bg-surface-2/70 p-1 text-[13px] font-medium">
        <ModeButton active={mode === "code"} onClick={() => setMode("code")} icon={<MessageSquareText size={14} />} label={t("With a code")} />
        <ModeButton active={mode === "password"} onClick={() => setMode("password")} icon={<KeyRound size={14} />} label={t("With a password")} />
      </div>
      <div>
        <label htmlFor={`${ids}-id`} className="text-[12px] text-muted">{isMainland() ? t("Mainland China phone number or e-mail") : t("E-mail (or a mainland China phone number)")}</label>
        <input
          id={`${ids}-id`}
          value={identifier}
          onChange={(e) => {
            setIdentifier(e.target.value);
            setSent(false);
          }}
          inputMode={identifierInputMode(identifier)}
          autoComplete="username"
          autoFocus={autoFocus}
          placeholder={t("138 0000 0000 or you@example.com")}
          className={cx(inputCls, "mt-1")}
        />
        {mode === "code" && !sent && (!isMainland() || looksLikeForeignNumber(identifier)) && (
          <p className="mt-1.5 text-[12px] text-muted">{t("Text-message codes reach mainland-China numbers only. Use an e-mail address instead.")}</p>
        )}
      </div>
      {mode === "password" ? (
        <div>
          <label htmlFor={`${ids}-password`} className="text-[12px] text-muted">{t("Password")}</label>
          <input
            id={`${ids}-password`}
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            className={cx(inputCls, "mt-1")}
          />
          <p className="mt-1.5 text-[12px] text-muted">{t("No password yet? Use a code first; set one under Account.")}</p>
        </div>
      ) : (
        <>
          {sent && (
            <div>
              <label htmlFor={`${ids}-code`} className="text-[12px] text-muted">{t("The code you received")}</label>
              <input
                id={`${ids}-code`}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 8))}
                inputMode="numeric"
                autoComplete="one-time-code"
                placeholder="123456"
                autoFocus
                className={cx(inputCls, "mt-1 tracking-[0.3em]")}
              />
            </div>
          )}
          {inviteOpen ? (
            <div>
              <label htmlFor={`${ids}-invite`} className="text-[12px] text-muted">{t("Invite code (optional)")}</label>
              <input
                id={`${ids}-invite`}
                value={invite}
                onChange={(e) => setInvite(normalizeInvite(e.target.value))}
                autoComplete="off"
                placeholder="ABCD2345"
                className={cx(inputCls, "mt-1 tracking-[0.2em] uppercase")}
              />
              <p className="mt-1.5 text-[12px] text-muted">{t("A friend's code counts for a new account: you both get ¥{invite} more allowance.", { invite: (cfg.invite_bonus_cny ?? 5).toFixed(0) })}</p>
            </div>
          ) : (
            <button type="button" onClick={() => setInviteOpen(true)} className="text-[12px] text-muted underline-offset-2 hover:underline">
              {t("Have an invite code?")}
            </button>
          )}
        </>
      )}
      {error && <div className="rounded-2xl bg-rose-500/12 px-3 py-2 text-[12.5px] text-rose-700 dark:text-rose-300">{error}</div>}
      <div className="flex gap-2">
        {mode === "code" && sent ? (
          <>
            <button type="button" disabled={busy !== null} onClick={() => void sendCode()} className={secondaryBtn}>
              {t("Send again")}
            </button>
            <button type="submit" disabled={busy !== null || code.trim().length < 4} className={cx(primaryBtn, "flex-1 py-3")}>
              {busy ? <Loader2 size={15} className="animate-spin" /> : null} {label}
            </button>
          </>
        ) : mode === "code" ? (
          <button type="submit" disabled={busy !== null || !identifier.trim()} className={cx(primaryBtn, "flex-1 py-3")}>
            {busy === "code" ? <Loader2 size={15} className="animate-spin" /> : null} {t("Send me a code")}
          </button>
        ) : (
          <button type="submit" disabled={busy !== null || !identifier.trim() || !password} className={cx(primaryBtn, "flex-1 py-3")}>
            {busy ? <Loader2 size={15} className="animate-spin" /> : null} {label}
          </button>
        )}
      </div>
    </form>
  );
}

function ModeButton({ active, onClick, icon, label }: { active: boolean; onClick: () => void; icon: React.ReactNode; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cx("flex items-center justify-center gap-1.5 rounded-xl px-2 py-2 transition", active ? "bg-surface text-fg shadow-sm" : "text-muted hover:text-fg")}
    >
      {icon} {label}
    </button>
  );
}
