/**
 * The own-key provider catalogue (contract C11): one list of providers with what each one
 * covers — chat, vision (the hands), image (pictures), video (clips) — and the rule that a
 * feature whose capability no configured provider has is unavailable with one sentence.
 *
 * The facts come from the runtime (`GET /api/providers`, which also says which slots are
 * configured today and which capabilities that gives) and, when the runtime is older or
 * unreachable, from the bundled copy of `nanomuse/llm/providers.json` — the same file the
 * relay, the desktop and the phones read.
 */
import { useEffect, useState } from "react";
import catalogue from "../../nanomuse/llm/providers.json";
import { api } from "./api";
import { isMainland } from "./region";
import type { Capability, CatalogueProvider, CloudAccount, ProvidersView } from "./types";

export type { Capability, CatalogueProvider, ProvidersView };
export const CAPABILITIES: Capability[] = ["chat", "vision", "image", "video"];

export type Region = "cn" | "global";

export const CATALOGUE: CatalogueProvider[] = (catalogue as { providers: CatalogueProvider[] }).providers;

/** The local servers: listed apart, never first. */
export const LOCAL_IDS = ["ollama", "lm-studio", "vllm"];

/** Who goes first for a region: the mainland to Bailian (one key for all four), elsewhere OpenRouter then OpenAI. */
const FIRST: Record<Region, string[]> = { cn: ["bailian"], global: ["openrouter", "openai"] };

/**
 * The runtime's preset id for a catalogue id (the Connections card's provider tiles are
 * the runtime's presets, named before the catalogue existed).
 */
const PRESET_OF: Record<string, string> = { bailian: "qwen", moonshot: "kimi", zhipu: "glm", volcengine: "doubao" };
export function presetFor(id: string): string {
  return PRESET_OF[id] ?? id;
}
/** …and back: the catalogue entry a preset tile stands for. */
export function catalogueIdFor(preset: string): string {
  return Object.entries(PRESET_OF).find(([, p]) => p === preset)?.[0] ?? (preset === "openai_responses" ? "openai" : preset);
}

/** The person's region for the catalogue: mainland China → `cn`, everyone else → `global`. */
export function regionOf(account?: Pick<CloudAccount, "channel" | "region" | "signed_in"> | null): Region {
  return isMainland(account) ? "cn" : "global";
}

/** The provider's name in the UI language. */
export function providerName(p: Pick<CatalogueProvider, "name" | "name_zh">, locale: string): string {
  return locale === "zh-CN" ? p.name_zh || p.name : p.name;
}

/** The base URL and key page for the region (Kimi and MiniMax have two editions). */
export function editionFor(p: CatalogueProvider, region: Region): { base_url: string; key_url: string } {
  if (region === "global" && p.regions.includes("global") && p.base_url_global) {
    return { base_url: p.base_url_global, key_url: p.key_url_global || p.key_url };
  }
  return { base_url: p.base_url, key_url: p.key_url };
}

function fits(p: CatalogueProvider, region: Region): boolean {
  return p.regions.includes(region);
}

/**
 * The providers for a region, in order: the region's first picks, then the rest by how
 * much the key covers; local servers and "custom" left out. `cap` keeps only those that
 * have the capability.
 */
export function providersFor(region: Region, cap?: Capability, list: CatalogueProvider[] = CATALOGUE): CatalogueProvider[] {
  const byId = new Map(list.map((p) => [p.id, p]));
  const first = FIRST[region].map((id) => byId.get(id)).filter((p): p is CatalogueProvider => !!p && fits(p, region));
  const rest = list
    .filter((p) => !first.includes(p) && !LOCAL_IDS.includes(p.id) && p.id !== "custom" && fits(p, region))
    .sort((a, b) => b.capabilities.length - a.capabilities.length);
  const all = [...first, ...rest];
  return cap ? all.filter((p) => p.capabilities.includes(cap)) : all;
}

/** A plan a person may already pay for, and whether this client can sign in with it. */
export interface Plan {
  id: "chatgpt" | "claude" | "kimi" | "openrouter";
  provider: string;
  name: string;
  auth: string;
  /** this web console has the flow (ChatGPT, through the runtime) */
  here: boolean;
  covers: Capability[];
}
export function plans(list: CatalogueProvider[] = CATALOGUE): Plan[] {
  const defs: Array<Omit<Plan, "covers">> = [
    { id: "chatgpt", provider: "openai", name: "ChatGPT", auth: "oauth-chatgpt", here: true },
    { id: "claude", provider: "anthropic", name: "Claude", auth: "oauth-claude", here: false },
    { id: "kimi", provider: "moonshot", name: "Kimi", auth: "device-kimi", here: false },
    { id: "openrouter", provider: "openrouter", name: "OpenRouter", auth: "oauth-openrouter", here: false },
  ];
  const out: Plan[] = [];
  for (const d of defs) {
    const p = list.find((q) => q.id === d.provider);
    if (!p || !p.auth.includes(d.auth)) continue;
    out.push({ ...d, covers: p.auth_capabilities?.[d.auth] ?? p.capabilities });
  }
  return out;
}

/** The noun for a capability, as the sentences use it. */
export function capabilityNoun(t: (s: string) => string, cap: Capability): string {
  switch (cap) {
    case "chat":
      return t("Chat");
    case "vision":
      return t("Hands");
    case "image":
      return t("Pictures");
    case "video":
      return t("Clips");
  }
}

/** A short "covers chat, hands, pictures" for a provider row. */
export function coversLine(t: (s: string, v?: Record<string, string | number>) => string, caps: Capability[]): string {
  const names = CAPABILITIES.filter((c) => caps.includes(c)).map((c) => capabilityNoun(t, c).toLowerCase());
  return t("covers {list}", { list: names.join(t(", ")) });
}

/**
 * The one sentence for a feature nobody configured can do (contract C11):
 * *Pictures need a provider with image models: Bailian, OpenAI, Gemini or OpenRouter (how).*
 * The names are the region's providers with the capability, four at most.
 */
export function unavailableLine(t: (s: string, v?: Record<string, string | number>) => string, cap: Capability, region: Region, locale: string, list: CatalogueProvider[] = CATALOGUE): string {
  const names = providersFor(region, cap, list)
    .slice(0, 4)
    .map((p) => providerName(p, locale));
  const last = names.pop() ?? "";
  const joined = names.length ? `${names.join(t(", "))}${t(" or ")}${last}` : last;
  switch (cap) {
    case "image":
      return t("Pictures need a provider with image models: {providers}.", { providers: joined });
    case "video":
      return t("Clips need a provider with video models: {providers}.", { providers: joined });
    case "vision":
      return t("The hands need a model that sees pictures: {providers}.", { providers: joined });
    case "chat":
      return t("Chat needs a model: {providers}.", { providers: joined });
  }
}

/** The guide every unavailable line links to. */
export const OWN_KEY_DOCS_URL = "https://nanomuse.cn/own-key";

/**
 * The runtime's view when it has one; else the bundled catalogue with nothing known about
 * what is configured (`capabilities: null` — no gating, the runtime of before decides).
 */
export interface ProvidersInfo extends Omit<ProvidersView, "capabilities" | "region"> {
  region: Region | "";
  capabilities: Capability[] | null;
  source: "runtime" | "bundled";
}

let cached: ProvidersInfo | null = null;
let inflight: Promise<ProvidersInfo> | null = null;
let generation = 0;

export async function loadProviders(force = false): Promise<ProvidersInfo> {
  if (cached && !force) return cached;
  if (inflight && !force) return inflight;
  const mine = ++generation;
  const load = api
    .providers()
    .then((v) => ({ ...v, capabilities: v.capabilities ?? null, source: "runtime" as const }))
    .catch(() => ({
      providers: CATALOGUE,
      region: "" as const,
      configured: {},
      capabilities: null,
      unavailable: {},
      source: "bundled" as const,
    }))
    .then((v) => {
      // an invalidation since this load started (a sign-out, a finished sign-in)
      // must not have the old view written back over it
      if (mine === generation) cached = v;
      if (inflight === load) inflight = null;
      return v;
    });
  inflight = load;
  return load;
}

/** Forget what was loaded (after the model was changed or a sign-in finished). */
export function invalidateProviders(): void {
  cached = null;
  generation += 1;
}

export function useProviders(version = 0): ProvidersInfo | null {
  const [info, setInfo] = useState<ProvidersInfo | null>(cached);
  useEffect(() => {
    let alive = true;
    void loadProviders(version > 0).then((v) => alive && setInfo(v));
    return () => {
      alive = false;
    };
  }, [version]);
  return info;
}

/** Whether the configured providers cover a capability; `null` = unknown (older runtime). */
export function has(info: ProvidersInfo | null, cap: Capability): boolean | null {
  if (!info || info.capabilities === null) return null;
  return info.capabilities.includes(cap);
}
