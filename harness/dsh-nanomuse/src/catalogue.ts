/**
 * The own-key catalogue's shapes and the pure rules over them (contract C11), shared by both
 * halves: the host (`src/providers.ts`, which adds the parsing, the model listing and the
 * ChatGPT sign-in — Node only) and the browser (`src/client/OwnKey.tsx`, which draws the rows
 * in the groups `waysOn` gives). Nothing here touches Node or the DOM, so the two halves order
 * the rows the same way and name the same providers in the gate's one sentence.
 */

export type Capability = 'chat' | 'vision' | 'image' | 'video'
export const CAPABILITIES: readonly Capability[] = ['chat', 'vision', 'image', 'video']

export type Protocol = 'openai' | 'openai-responses' | 'anthropic' | 'gemini'
export type Region = 'cn' | 'global'
/** How a person gets in: a key, a sign-in flow a client may support, nothing (a local server). */
export type Auth = 'key' | 'oauth-chatgpt' | 'oauth-claude' | 'oauth-openrouter' | 'device-kimi' | 'none'

/** The thinking levels the harness's picker can offer (pi-ai's names, `off` aside). */
export type ThinkingLevel = 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max'
export const THINKING_LEVELS: readonly ThinkingLevel[] = ['minimal', 'low', 'medium', 'high', 'xhigh', 'max']

/**
 * How a vendor takes the chosen level on the wire (the catalogue's `reasoning.wire`):
 * `reasoning_effort` (the OpenAI-compatible top-level field), `thinking+reasoning_effort`
 * (`thinking: {type: "enabled"}` beside it: DeepSeek, Zhipu), `reasoning.effort` (OpenRouter's
 * nested object), `output_config.effort` (Anthropic's Messages API with adaptive thinking).
 */
export type ReasoningWire = 'reasoning_effort' | 'thinking+reasoning_effort' | 'reasoning.effort' | 'output_config.effort'
export const REASONING_WIRES: readonly ReasoningWire[] = ['reasoning_effort', 'thinking+reasoning_effort', 'reasoning.effort', 'output_config.effort']

/** The levels a vendor documents for the models an id pattern names; `default` is what the vendor applies when nothing is sent (`none`: no thinking). */
export interface ReasoningRule {
  /** A regular expression over the model id, matched without regard to case. */
  models: string
  levels: ThinkingLevel[]
  default?: ThinkingLevel | 'none'
}

/**
 * A provider's thinking-level facts (`reasoning` in `providers.json`), verified against the page
 * `doc` names: the wire shape, the documented levels per model pattern (first match wins), or
 * `listed` when the endpoint's own model list says which levels each model takes (OpenRouter).
 */
export interface ReasoningHint {
  doc: string
  wire: ReasoningWire
  rules: ReasoningRule[]
  listed: boolean
}

/** One row of the catalogue (`providers.json`). */
export interface ProviderEntry {
  id: string
  name: string
  name_zh: string
  protocol: Protocol
  base_url: string
  /** A second edition outside mainland China (Kimi, MiniMax), with its own console. */
  base_url_global?: string
  key_url: string
  key_url_global?: string
  /** What a key of theirs looks like (`sk-…`), shown as the field's placeholder. */
  key_hint: string
  auth: Auth[]
  /** A sign-in that gives less than the key does (the ChatGPT plan: chat and vision, no pictures). */
  auth_capabilities: Partial<Record<Auth, Capability[]>>
  regions: Region[]
  capabilities: Capability[]
  /** `custom`: the person says what the endpoint can do. */
  user_capabilities: boolean
  defaults: Partial<Record<'chat' | 'hands' | 'image' | 'video', string>>
  note: string
  note_zh: string
  /** The month the row was checked against the vendor's documentation; empty for a draft. */
  verified: string
  /** How the vendor takes a thinking level, when it documents one; absent: no control is offered. */
  reasoning?: ReasoningHint
  /**
   * The header the vendor's docs want one stable id per conversation in (OpenCode Go:
   * `x-opencode-session`). The model adapter's catalog route of the same id sends it, so such a
   * row is written as that route (`ownProviderRow`, `catalogRoute`).
   */
  session_header?: string
}

/** The levels of a listed or hinted model, as the pickers may offer them. */
export interface ModelReasoning {
  levels: ThinkingLevel[]
  default?: ThinkingLevel | 'none'
}

/**
 * The thinking levels a model takes: what the endpoint's own list said about it (OpenRouter's
 * `reasoning.supported_efforts`) when the hint reads the list, else the first rule whose pattern
 * matches the id. Nothing for a model the vendor documents no control for.
 */
export function reasoningFor(hint: ReasoningHint | undefined, modelId: string, listed?: ModelReasoning): ModelReasoning | undefined {
  if (!hint) return undefined
  if (hint.listed && listed?.levels.length) return listed
  for (const rule of hint.rules) {
    let re: RegExp
    try {
      re = new RegExp(rule.models, 'i')
    } catch {
      continue
    }
    if (re.test(modelId) && rule.levels.length) return { levels: rule.levels, ...(rule.default ? { default: rule.default } : {}) }
  }
  return undefined
}

/** The base URL for a region: the global edition when the entry has one and the person is outside mainland China. */
export function baseUrlFor(entry: Pick<ProviderEntry, 'base_url' | 'base_url_global'>, region: Region): string {
  return (region === 'global' && entry.base_url_global) || entry.base_url
}

/** Where the key is handed out, by region. */
export function keyUrlFor(entry: Pick<ProviderEntry, 'key_url' | 'key_url_global'>, region: Region): string {
  return (region === 'global' && entry.key_url_global) || entry.key_url
}

/** What a sign-in flow gives, when the catalogue says it gives less than the key. */
export function capabilitiesForAuth(entry: Pick<ProviderEntry, 'capabilities' | 'auth_capabilities'>, auth: Auth): Capability[] {
  return entry.auth_capabilities[auth] ?? entry.capabilities
}

/** The sign-in flows this desktop supports (the phones have the others from upstream OpenMinis). */
export const DESKTOP_FLOWS: readonly Auth[] = ['oauth-chatgpt']

/** The groups the "ways on" and the own-key step show, in order (C11). */
export interface WaysOn {
  /** The person's region first: mainland China → Bailian (one key for all four); elsewhere → OpenRouter, then OpenAI. */
  first: ProviderEntry[]
  /** "Sign in with a subscription you already pay for": the flows this client supports. */
  signIn: ProviderEntry[]
  /** The rest that work where the person is, the ones that can do more first. */
  rest: ProviderEntry[]
  /** Servers on this computer (no key): Ollama, LM Studio, vLLM. */
  local: ProviderEntry[]
  /** Any OpenAI-compatible endpoint by hand. */
  custom: ProviderEntry | undefined
}

const FIRST: Record<Region, string[]> = { cn: ['bailian'], global: ['openrouter', 'openai'] }

/** A server on this computer: the catalogue points it at a loopback address (Ollama, LM Studio, vLLM). */
export function isLocal(entry: Pick<ProviderEntry, 'base_url' | 'auth'>): boolean {
  return /^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(:|\/|$)/.test(entry.base_url) && entry.auth.includes('none')
}

/** The entries that work where the person is (an entry naming no region works everywhere). */
export function entriesFor(catalogue: ProviderEntry[], region: Region): ProviderEntry[] {
  return catalogue.filter((p) => p.regions.includes(region) || p.regions.length === 0)
}

/** No vendor is "recommended": the person's region decides who comes first, what each one covers decides the rest. */
export function waysOn(catalogue: ProviderEntry[], region: Region, flows: readonly Auth[] = DESKTOP_FLOWS): WaysOn {
  const here = entriesFor(catalogue, region)
  const firstIds = FIRST[region]
  const first = firstIds.map((id) => here.find((p) => p.id === id)).filter((p): p is ProviderEntry => Boolean(p))
  const taken = new Set(first.map((p) => p.id))
  const signIn = here.filter((p) => !taken.has(p.id) && p.auth.some((a) => flows.includes(a)))
  const local = here.filter((p) => isLocal(p))
  const custom = here.find((p) => p.id === 'custom')
  for (const p of [...signIn, ...local]) taken.add(p.id)
  if (custom) taken.add(custom.id)
  const rest = here
    .filter((p) => !taken.has(p.id))
    .sort((a, b) => b.capabilities.length - a.capabilities.length || a.name.localeCompare(b.name))
  return { first, signIn, rest, local, custom }
}

/** The region a client assumes: the relay's word when it has one (`cn` / `intl`), else the UI language as a hint. */
export function regionOf(relaySaid: string | undefined, uiLanguage: string): Region {
  if (relaySaid === 'cn') return 'cn'
  if (relaySaid && relaySaid !== 'cn') return 'global'
  return uiLanguage.toLowerCase().startsWith('zh') ? 'cn' : 'global'
}

/** One source of capability, as the gate counts them: the cloud account, an own-key row, the ChatGPT sign-in. */
export interface CapabilitySource {
  id: string
  label: string
  capabilities: Capability[]
}

/** What the configured sources can do between them (C11, the rule). */
export function capabilitiesOf(sources: CapabilitySource[]): Set<Capability> {
  const out = new Set<Capability>()
  for (const s of sources) for (const c of s.capabilities) out.add(c)
  return out
}

/** Which catalogue entries have a capability where the person is — the sentence "Pictures need a provider with image models — …" names them; never `custom`. */
export function providersWith(catalogue: ProviderEntry[], capability: Capability, region: Region): ProviderEntry[] {
  return entriesFor(catalogue, region).filter((p) => p.capabilities.includes(capability) && p.id !== 'custom')
}

/** What the gate looks at to word its sentence: what is configured between them, and whether the ChatGPT sign-in is all there is. */
export interface GateView {
  capabilities: Capability[]
  configured: { provider: string }[]
  cloud: { signedIn: boolean }
  chatgpt: { signedIn: boolean }
}

/** The ChatGPT sign-in is the only thing configured (no account, no key): it covers chat and the hands, not pictures or clips. */
export function chatGptOnly(view: Pick<GateView, 'configured' | 'cloud' | 'chatgpt'>): boolean {
  return view.chatgpt.signedIn && !view.cloud.signedIn && view.configured.every((p) => p.provider === 'chatgpt')
}

/** The sentences the gate can say, as the browser half's locale keys. */
export type UnavailableKey = 'ownKeyNoChat' | 'ownKeyNoVision' | 'ownKeyNoImage' | 'ownKeyNoVideo' | 'ownKeyChatGptNoMedia'

/**
 * Which one sentence a capability nobody configured has gets (C11): the capability's own,
 * naming who could; with only the ChatGPT sign-in, that pictures and clips are not covered by
 * it. Null when something configured has the capability — nothing is said.
 */
export function unavailableKey(view: GateView, capability: Capability): UnavailableKey | null {
  if (view.capabilities.includes(capability)) return null
  if ((capability === 'image' || capability === 'video') && chatGptOnly(view)) return 'ownKeyChatGptNoMedia'
  return capability === 'image' ? 'ownKeyNoImage' : capability === 'video' ? 'ownKeyNoVideo' : capability === 'vision' ? 'ownKeyNoVision' : 'ownKeyNoChat'
}

/** The own-key step of the first run is done: a key was saved, or the ChatGPT sign-in finished. */
export function ownKeyStepDone(view: Pick<GateView, 'configured' | 'chatgpt'>): boolean {
  return view.configured.length > 0 || view.chatgpt.signedIn
}
