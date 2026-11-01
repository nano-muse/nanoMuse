/**
 * Where the person is, for the "ways on" copy (contracts C5 and C11): mainland China gets
 * Alibaba Cloud Bailian first (its console only signs up accounts from the mainland);
 * everyone else gets OpenRouter first — one account, one key, pay as you go. The facts
 * about each (key page, endpoint, default models, what the key covers) come from the
 * catalogue `nanomuse/llm/providers.json`, the one file every client reads.
 *
 * Mainland = the UI language is 简体中文, or the account was signed in with a phone
 * number (codes reach mainland numbers only), or the relay says `region: "cn"`. A relay
 * that does not say yet is fine: the other two signs still work.
 */
import catalogue from "../../nanomuse/llm/providers.json";
import { getLocale } from "./i18n";
import type { Capability, CatalogueProvider, CloudAccount, ProviderPreset } from "./types";

export function isMainland(account?: Pick<CloudAccount, "channel" | "region" | "signed_in"> | null): boolean {
  if (account?.region) return account.region === "cn";
  if (account?.signed_in && account.channel === "sms") return true;
  return getLocale() === "zh-CN";
}

/** A number with a country code that is not mainland China's: no text message can reach it. */
export function looksLikeForeignNumber(value: string): boolean {
  // 86 is the only country code that starts with 86, spaced or not: "+8613800138000" is
  // as mainland as "+86 138 0000 0000", which the word boundary alone never matched
  return /^\s*(\+|00)(?!86)\d/.test(value);
}

export interface OwnKeyWay {
  /** the catalogue id: "bailian" or "openrouter" */
  id: "bailian" | "openrouter";
  /** the preset id in Connections: "qwen" (Bailian) or "openrouter" */
  preset: "qwen" | "openrouter";
  label: string;
  keyUrl: string;
  baseUrl: string;
  chatModel: string;
  guiModel: string;
  /** what one key there covers (contract C11) */
  covers: Capability[];
}

const BY_ID = new Map((catalogue as { providers: CatalogueProvider[] }).providers.map((p) => [p.id, p]));

function wayFrom(id: "bailian" | "openrouter", preset: "qwen" | "openrouter"): OwnKeyWay {
  const p = BY_ID.get(id);
  if (!p) throw new Error(`providers.json has no ${id}`);
  return {
    id,
    preset,
    label: p.name,
    keyUrl: p.key_url,
    baseUrl: p.base_url,
    chatModel: p.defaults.chat ?? "",
    guiModel: p.defaults.hands ?? p.defaults.chat ?? "",
    covers: p.capabilities,
  };
}

/** The region's first pick, read from the catalogue: Bailian on the mainland, OpenRouter elsewhere. */
const BAILIAN = wayFrom("bailian", "qwen");
const OPENROUTER = wayFrom("openrouter", "openrouter");

/** The own-key provider to lead with for this person. */
export function ownKeyWay(account?: Pick<CloudAccount, "channel" | "region" | "signed_in"> | null): OwnKeyWay {
  return isMainland(account) ? BAILIAN : OPENROUTER;
}

/**
 * The one sentence under "Use your own model key" (contracts C5 and C11): the region's
 * first pick and what one key there covers. English first, then 简体中文 through the
 * dictionary.
 */
export function ownKeyLine(t: (s: string) => string, account?: Pick<CloudAccount, "channel" | "region" | "signed_in"> | null): string {
  return isMainland(account)
    ? t("Alibaba Cloud Bailian is a good start: a new account comes with a free quota, set-up takes about two minutes, and one key covers chat, the hands, pictures and clips.")
    : t("Alibaba Cloud Bailian only signs up accounts from mainland China. Outside, OpenRouter is the easy way: one account, one key, pay as you go, for chat, the hands and pictures; clips need Bailian.");
}

/** Whether a model id says it sees pictures (the runtime's rule, mirrored for the pickers). */
export function modelSees(id: string): boolean | null {
  const name = (id || "").toLowerCase().split("/").pop() ?? "";
  if (!name) return null;
  if (name.startsWith("deepseek")) return /v4\.1|vision|ocr/.test(name);
  if (name.startsWith("qwen")) return name.includes("-vl") || name.startsWith("qwen3.8") ? true : null;
  return null;
}

/** The presets in the order to show them: the region's own-key provider first. */
export function orderPresets(ids: string[], presets: Record<string, ProviderPreset>, account?: Pick<CloudAccount, "channel" | "region" | "signed_in"> | null): string[] {
  const first = ownKeyWay(account).preset;
  if (!ids.includes(first)) return ids;
  const mainland = isMainland(account);
  // outside the mainland, the mainland-only vendor goes last in its group
  const rest = ids.filter((id) => id !== first);
  if (mainland) return [first, ...rest];
  const cn = rest.filter((id) => presets[id]?.region === "cn");
  return [first, ...rest.filter((id) => !cn.includes(id)), ...cn];
}
