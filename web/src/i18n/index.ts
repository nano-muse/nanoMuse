/**
 * Small gettext-style i18n: the English source text is the key, `t()` looks it up in the
 * dictionary of the current locale and falls back to the key itself. No dependency, no
 * extraction step — a new string is just written in English and added to zh-CN.ts.
 *
 * The locale is a device setting (localStorage), separate from the agent's reply language
 * in Settings: "auto" follows the browser, otherwise English or 简体中文.
 */
import { useSyncExternalStore } from "react";
import zhCN from "./zh-CN";

export type Locale = "en" | "zh-CN";
export type LocaleSetting = Locale | "auto";

export const LOCALES: Array<{ value: LocaleSetting; label: string }> = [
  { value: "auto", label: "Auto" },
  { value: "en", label: "English" },
  { value: "zh-CN", label: "简体中文" },
];

const STORAGE_KEY = "nanomuse_locale";
const DICTS: Record<Locale, Record<string, string>> = { en: {}, "zh-CN": zhCN };

function load(): LocaleSetting {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === "en" || v === "zh-CN" || v === "auto") return v;
  } catch {
    // private mode / no storage: stay on auto
  }
  return "auto";
}

let setting: LocaleSetting = load();
const listeners = new Set<() => void>();

/** What the browser is set to, reduced to a locale we have. */
export function detectLocale(): Locale {
  const langs = typeof navigator === "undefined" ? [] : [navigator.language, ...(navigator.languages ?? [])];
  return langs.some((l) => /^zh\b/i.test(l ?? "")) ? "zh-CN" : "en";
}

export function getLocaleSetting(): LocaleSetting {
  return setting;
}

export function getLocale(): Locale {
  return setting === "auto" ? detectLocale() : setting;
}

export function setLocaleSetting(next: LocaleSetting): void {
  setting = next;
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // fine — the choice lasts for this page then
  }
  applyLang();
  listeners.forEach((fn) => fn());
}

/** `<html lang>` follows the locale so fonts, hyphenation and screen readers agree with the text. */
export function applyLang(): void {
  if (typeof document !== "undefined") document.documentElement.lang = getLocale();
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Re-renders the component when the locale changes. */
export function useLocale(): Locale {
  return useSyncExternalStore(subscribe, getLocale, getLocale);
}

export function useLocaleSetting(): LocaleSetting {
  return useSyncExternalStore(subscribe, getLocaleSetting, getLocaleSetting);
}

export type Vars = Record<string, string | number>;

function interpolate(text: string, vars?: Vars): string {
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m));
}

/**
 * Translate `key` (the English text) into the current locale. `{name}` placeholders are
 * filled from `vars`. Unknown keys come back as themselves, so English never breaks.
 */
export function t(key: string, vars?: Vars): string {
  const dict = DICTS[getLocale()];
  return interpolate(dict[key] ?? key, vars);
}

/**
 * The server labels background work in English ("Working on your goal: Run a 10k",
 * "Check-in: …", "Reminder: …", "Routine: …", "Tidied memory"). Translate the fixed part
 * and keep what the user wrote.
 */
export function localLabel(label: string): string {
  const rest = (prefix: string) => ({ title: label.slice(prefix.length) });
  if (label.startsWith("Working on your goal: ")) {
    return t("Working on your goal: {title}", rest("Working on your goal: "));
  }
  if (label.startsWith("Check-in: ")) return t("Check-in: {title}", rest("Check-in: "));
  if (label.startsWith("Reminder: ")) return t("Reminder: {title}", rest("Reminder: "));
  if (label.startsWith("Routine: ")) return t("Routine: {title}", rest("Routine: "));
  if (label.startsWith("New mail: ")) return t("New mail: {title}", rest("New mail: "));
  if (label.startsWith("Coming up: ")) return t("Coming up: {title}", rest("Coming up: "));
  if (label.startsWith("Webhook: ")) return t("Webhook: {title}", rest("Webhook: "));
  return label === "Tidied memory" ? t("Tidied memory") : label;
}

/**
 * Why the Sentinel asked, in the person's language and words. The runtime's reasons are
 * built from its settings (`'shell' is in always_ask_tools`, `risk level is 'sensitive'
 * (mode=ask)`); the shapes it uses are known, so the fixed part is translated and the
 * tool, the risk and the destination are kept. A shape not known here is shown as it came.
 */
export function localReason(reason: string): string {
  let m = /^'([^']+)' is in always_ask_tools$/.exec(reason);
  if (m) return t("{tool} is on your always-ask list", { tool: m[1] });
  m = /^'([^']+)' is in always_allow_tools$/.exec(reason);
  if (m) return t("{tool} is on your always-allow list", { tool: m[1] });
  m = /^'([^']+)' is in sentinel\.deny_tools$/.exec(reason);
  if (m) return t("{tool} is switched off in your settings", { tool: m[1] });
  m = /^risk level is '(\w+)' \(mode=(\w+)\)$/.exec(reason);
  if (m) return t("an action rated {risk}, in {mode} mode", { risk: t(m[1]), mode: t(m[2]) });
  if (reason === "auto mode: approval skipped") return t("auto mode: not asked");
  m = /^covered by your '([^']+)' permission for (.+)$/.exec(reason);
  if (m) return t("covered by your {scope} permission for {key}", { scope: t(m[1]), key: m[2] });
  m = /^private data was read earlier in this conversation and '([^']+)' can send data to (.+), which is not on sentinel\.egress_allowlist$/.exec(reason);
  if (m) return t("private data was read earlier in this conversation, and {tool} could send it to {target}, which is not on your allowed list", { tool: m[1], target: m[2] });
  return t(reason);
}

/**
 * A sentence from the server that carries a number (`the file is larger than 25 MB`):
 * the fixed part is translated, the number kept. Anything else goes through `t()`.
 */
export function localDetail(detail: string): string {
  const m = /^the file is larger than (\d+) MB$/.exec(detail);
  if (m) return t("The file is larger than {n} MB.", { n: m[1] });
  return t(detail);
}

/** `t` bound to the live locale: the component re-renders when the language changes. */
export function useT(): typeof t {
  useLocale();
  return t;
}

/** Locale tag for Intl / toLocale*String, so dates and numbers follow the UI language. */
export function intlLocale(): string {
  return getLocale() === "zh-CN" ? "zh-CN" : "en-US";
}

/** Names of translated keys, for tests and for spotting strings that lack a translation. */
export function dictionaryKeys(locale: Locale): string[] {
  return Object.keys(DICTS[locale]);
}
