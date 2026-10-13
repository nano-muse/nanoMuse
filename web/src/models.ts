/**
 * The model slots as the web console shows them (the Models contract, 0.1.41): a row's
 * value as `<provider> · <model>`, and what the picker of one capability offers — the
 * nanoMuse Cloud group when signed in, the chat model's provider when it has the
 * capability (its key serves), then every catalogue provider that has it (a key to add).
 * Pure functions; `models.test.ts` checks them.
 */
import type { ModelGroup } from "./model-list";
import { CATALOGUE, providerName, providersFor, type Capability, type Region } from "./providers";
import { modelSees } from "./region";
import type { CatalogueProvider, CustomEndpoint, MediaSlotData } from "./types";

/** what the account's model is called when it stands in a provider list (the runtime's id) */
export const CLOUD_ID = "nanomuse_cloud";
/** the vault reference the runtime keeps the account key under; a slot set to the relay names it */
export const CLOUD_KEY_REF = "{{vault:NANOMUSE_CLOUD_KEY}}";
/** the picker's entry for a host the catalogue does not list */
export const CUSTOM_ID = "custom";
/** a picker value or provider tile that names a custom endpoint of the runtime's list: `endpoint:<id>` (#294) */
export const ENDPOINT_PREFIX = "endpoint:";
/** the protocols a slot's `provider` may be instead of a catalogue id */
const PROTOCOLS = ["openai", "openai_responses"];

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.toLowerCase();
  } catch {
    return "";
  }
}

/** the picker value that stands for an endpoint of the list */
export function endpointChoice(id: string): string {
  return ENDPOINT_PREFIX + id;
}

/** the endpoint id a picker value names; null for anything else */
export function endpointOf(value: string): string | null {
  return value.startsWith(ENDPOINT_PREFIX) && value.length > ENDPOINT_PREFIX.length ? value.slice(ENDPOINT_PREFIX.length) : null;
}

/** what an endpoint is called in a row or a tile: its name, else its host (with the port when it has one) */
export function endpointLabel(e: Pick<CustomEndpoint, "label" | "base_url">): string {
  if (e.label.trim()) return e.label.trim();
  try {
    return new URL(e.base_url).host;
  } catch {
    return e.base_url;
  }
}

function endpointNamed(id: string | undefined, endpoints: readonly CustomEndpoint[]): CustomEndpoint | null {
  return id ? (endpoints.find((e) => e.id === id) ?? null) : null;
}

/**
 * One picker group per endpoint of the list for the hands model: the endpoint's name and
 * the models it serves, less those known not to see pictures. `except` leaves out the
 * endpoint whose models the picker lists already (the chat model's own).
 */
export function endpointGroups(endpoints: readonly CustomEndpoint[], except = ""): ModelGroup[] {
  return endpoints
    .filter((e) => e.id !== except && e.models.length)
    .map((e) => ({
      key: endpointChoice(e.id),
      label: endpointLabel(e),
      rows: e.models.filter((m) => modelSees(m) !== false).map((id) => ({ id, name: id })),
    }))
    .filter((g) => g.rows.length);
}

/**
 * The catalogue entry a slot stands on: the id `provider` names, else the entry whose host
 * `baseUrl` is (a regional subdomain counts); null for a protocol with an unlisted host.
 */
export function entryFor(provider: string, baseUrl: string, list: CatalogueProvider[] = CATALOGUE): CatalogueProvider | null {
  if (provider && !PROTOCOLS.includes(provider)) return list.find((p) => p.id === provider) ?? null;
  const host = hostOf(baseUrl);
  if (!host) return null;
  const hosts = (p: CatalogueProvider) => [p.base_url, p.base_url_global].map((u) => hostOf(u ?? "")).filter(Boolean);
  const exact = list.find((p) => hosts(p).includes(host));
  if (exact) return exact;
  return (
    list.find((p) =>
      hosts(p).some((h) => {
        const dot = h.indexOf(".");
        if (dot < 0) return false;
        // an apex-domain entry has no first label to strip; only a real
        // subdomain of it counts, else every host under the TLD would match
        return h.slice(dot + 1).includes(".") ? host.endsWith(h.slice(dot)) : host.endsWith(`.${h}`);
      }),
    ) ?? null
  );
}

/** The name a provider id shows in a row: nanoMuse Cloud, the catalogue's name, or the host. */
export function providerLabel(id: string, locale: string, baseUrl = "", list: CatalogueProvider[] = CATALOGUE): string {
  if (id === CLOUD_ID) return "nanoMuse Cloud";
  if (id === "chatgpt") return "ChatGPT";
  const entry = list.find((p) => p.id === id);
  if (entry && id !== CUSTOM_ID) return providerName(entry, locale);
  return hostOf(baseUrl) || id;
}

/** A row's value, `<provider> · <model>`; "" when nothing draws. A slot on an endpoint of the list reads its name. */
export function slotValue(
  slot: Pick<MediaSlotData, "effective_provider" | "effective_model" | "base_url" | "endpoint">,
  locale: string,
  list: CatalogueProvider[] = CATALOGUE,
  endpoints: readonly CustomEndpoint[] = [],
): string {
  if (!slot.effective_provider) return "";
  const own = endpointNamed(slot.endpoint, endpoints);
  const name = own ? endpointLabel(own) : providerLabel(slot.effective_provider, locale, slot.base_url, list);
  return slot.effective_model ? `${name} · ${slot.effective_model}` : name;
}

/** the hands slot as `GET /api/connections` reports it, the fields the row's value needs */
export interface HandsSlot {
  provider: string;
  provider_id?: string;
  base_url: string;
  effective_model?: string;
  effective_source?: "gui" | "chat" | "cloud";
  endpoint?: string;
}

/**
 * The hands row's value, `<provider> · <model>`, from the effective fields: nanoMuse Cloud
 * when the relay's hands model serves, the hands' own host when one is set, else the chat
 * model's provider. An endpoint of the list reads its name. "" while the runtime does not say.
 */
export function handsValue(
  gui: HandsSlot,
  llm: { provider: string; base_url: string; cloud?: boolean; endpoint?: string },
  locale: string,
  list: CatalogueProvider[] = CATALOGUE,
  endpoints: readonly CustomEndpoint[] = [],
): string {
  const model = gui.effective_model ?? "";
  if (!model) return "";
  // a protocol with an unlisted host is the host, never the OpenAI entry the word also names
  const labelOf = (provider: string, baseUrl: string) =>
    providerLabel(entryFor(provider, baseUrl, list)?.id ?? (PROTOCOLS.includes(provider) ? CUSTOM_ID : provider), locale, baseUrl, list);
  let name: string;
  const ownHands = endpointNamed(gui.endpoint, endpoints);
  const ownChat = endpointNamed(llm.endpoint, endpoints);
  if (gui.effective_source === "cloud") name = "nanoMuse Cloud";
  else if (gui.effective_source === "gui" && ownHands) name = endpointLabel(ownHands);
  else if (gui.effective_source === "gui" && (gui.provider_id || gui.base_url || !PROTOCOLS.includes(gui.provider || "openai")))
    name = gui.provider_id ? providerLabel(gui.provider_id, locale, gui.base_url, list) : labelOf(gui.provider, gui.base_url);
  else if (llm.cloud) name = "nanoMuse Cloud";
  else name = ownChat ? endpointLabel(ownChat) : labelOf(llm.provider, llm.base_url);
  return `${name} · ${model}`;
}

export interface MediaChoice {
  /** `nanomuse_cloud`, a catalogue id, `endpoint:<id>` for an endpoint of the list, or `custom` */
  value: string;
  label: string;
  group: "cloud" | "chat" | "endpoints" | "add";
  /** a key must be typed (the chat provider's key serves its own slot; the account needs none) */
  needsKey: boolean;
  entry: CatalogueProvider | null;
}

/**
 * What the picker of one slot offers, in order: nanoMuse Cloud when signed in; the chat
 * model's provider when it is an own provider with the capability; the endpoints of the
 * list (their own keys serve); then every catalogue provider with the capability for the
 * region (the chat provider not twice), and a host of one's own last. A provider without
 * the capability is not offered at all.
 */
export function mediaChoices(
  cap: Capability,
  opts: {
    signedIn: boolean;
    /** the chat slot: the relay (`cloud`), or an own provider by `provider` / `base_url` */
    chat: { provider: string; base_url: string; cloud: boolean };
    region: Region;
    locale: string;
    list?: CatalogueProvider[];
    /** the custom endpoints of the runtime's list (#294) */
    endpoints?: readonly CustomEndpoint[];
  },
): MediaChoice[] {
  const list = opts.list ?? CATALOGUE;
  const out: MediaChoice[] = [];
  if (opts.signedIn) out.push({ value: CLOUD_ID, label: "nanoMuse Cloud", group: "cloud", needsKey: false, entry: null });
  const chat = opts.chat.cloud ? null : entryFor(opts.chat.provider, opts.chat.base_url, list);
  if (chat && chat.capabilities.includes(cap)) {
    out.push({ value: chat.id, label: providerName(chat, opts.locale), group: "chat", needsKey: false, entry: chat });
  }
  for (const e of opts.endpoints ?? []) {
    out.push({ value: endpointChoice(e.id), label: endpointLabel(e), group: "endpoints", needsKey: false, entry: null });
  }
  for (const p of providersFor(opts.region, cap, list)) {
    if (p.id === chat?.id) continue;
    out.push({ value: p.id, label: providerName(p, opts.locale), group: "add", needsKey: true, entry: p });
  }
  out.push({ value: CUSTOM_ID, label: "", group: "add", needsKey: false, entry: null });
  return out;
}

/**
 * The picker's value for a slot as the runtime reports it: "" for nothing chosen, the
 * relay when the slot names its URL, an endpoint of the list by `endpoint:<id>`, the
 * catalogue id, else `custom`.
 */
export function currentChoice(slot: MediaSlotData, cloudBaseUrl: string): string {
  if (!slot.configured) return "";
  if (cloudBaseUrl && slot.base_url && hostOf(slot.base_url) === hostOf(cloudBaseUrl)) return CLOUD_ID;
  if (slot.endpoint) return endpointChoice(slot.endpoint);
  return slot.provider_id || CUSTOM_ID;
}
