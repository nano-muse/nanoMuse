/** The admin API's answers, the parts the console reads. The shapes are the relay's
 *  (service.py, analytics.py, stats.py, controls.py); a field the page does not draw is
 *  left out here. */

export interface KindRow {
  kind: string;
  requests: number;
  prompt_tokens: number;
  completion_tokens: number;
  charged: number;
  cost_cny: number;
}
export interface ModelRow extends KindRow {
  model: string;
}
export interface PeriodTotals {
  days?: number;
  requests: number;
  charged: number;
  prompt_tokens: number;
  completion_tokens: number;
  cost_cny: number;
  active_accounts: number;
  new_accounts: number;
  by_kind: KindRow[];
  by_model?: ModelRow[];
}
export interface Switch {
  enabled: boolean;
  updated_at: number | null;
  actor: string;
  note: string;
}
export interface RuntimeSettings {
  values: { allowance_cny: number; invite_bonus_cny: number; signup_open: boolean };
  env: { allowance_cny: number; invite_bonus_cny: number; signup_open: boolean };
  overridden: { allowance_cny: boolean; invite_bonus_cny: boolean; signup_open: boolean };
  below_allowance: number;
}
export interface Price {
  per_m_input: number;
  per_m_output: number;
  per_m_input_idle: number;
  per_m_output_idle: number;
  idle_hours: number[];
  per_m_cached_input: number;
  per_image: number;
  per_image_2k: number;
  per_image_in: number;
  per_second: number;
  per_second_res: Record<string, number>;
}
export interface Settings {
  runtime: RuntimeSettings;
  controls: Record<string, Switch>;
  paused: string[];
  repo_url: string;
  unlimited: boolean;
  signup_open: boolean;
  allowance_cny: number;
  allowance_usd: number;
  invite_bonus_cny: number;
  invitee_bonus_cny: number;
  contribute_bonus_cny: number;
  improve_default: boolean;
  usd_cny: number;
  day_offset_h: number;
  invite_url: string;
  own_key_docs: string;
  privacy_url: string;
  contributors: number;
  allowed_identifiers: string[];
  sender: string;
  password_min_len: number;
  per_minute_requests: number;
  signup_per_domain_day: number;
  signup_domain_allow: string[];
  models: string[];
  model_kinds: Record<string, string>;
  model_lanes: Record<string, string[]>;
  recommended_for: Record<string, string[]>;
  prices: Record<string, Price>;
  version: string;
}
export interface EventRow {
  id: number;
  account_id?: string;
  ts: number;
  kind: string;
  detail: string;
  ip: string;
  ua: string;
  hint?: string;
  identifier?: string;
  platform?: string;
}
export interface Geo {
  enabled: boolean;
  ready: boolean;
  families: string[];
  error: string;
  fetching: boolean;
  file: string;
}
export interface Overview {
  generated_at: number;
  day_start: number;
  accounts: { total: number; disabled: number; unlimited: number; with_password: number; live_keys: number; devices: number };
  today: PeriodTotals;
  week: PeriodTotals;
  period: PeriodTotals;
  signals_today: { sign_ins: number; sign_in_failures: number; budget_refusals: number; upstream_errors: number; content_rejected: number; calls: number };
  top_accounts: { account_id: string; hint: string; identifier: string; requests: number; charged: number; cost_cny: number }[];
  events: EventRow[];
  contributions: { accounts: number; samples: number };
  settings: Settings;
  online_devices: number;
  version: string;
  geo: Geo;
}
export interface SeriesDay {
  day: number;
  sign_ins: number;
  sign_in_failures: number;
  new_accounts: number;
  active_accounts: number;
  invites_used: number;
  contribute_on: number;
  calls: number;
  budget_refusals: number;
  upstream_errors: number;
  content_rejected: number;
}
export interface Series {
  generated_at: number;
  days: SeriesDay[];
  invites: { with_code: number; inviters: number; invited: number; contribute_bonuses: number };
  contributors: number;
  online_devices: number;
  web: Record<string, unknown> | null;
}

// -- live and analytics ---------------------------------------------------------------------

export interface LiveMinute {
  t: number;
  n: number;
  ok: number;
  errors: number;
  refused: number;
  timeouts: number;
  waited: number;
  tokens_out: number;
  tokens_in: number;
  p50_ttft: number;
  p50_total: number;
  p95_total: number;
  p95_wait: number;
}
export interface LiveSummary {
  requests: number;
  ok: number;
  errors: number;
  refused: number;
  by_status: Record<string, number>;
  accounts: number;
  p50_ttft_ms: number;
  p95_ttft_ms: number;
  p50_total_ms: number;
  p95_total_ms: number;
  p50_wait_ms: number;
  p95_wait_ms: number;
  waited_share: number;
  tokens_out: number;
  tokens_out_per_s: number;
  hands: number;
  with_images: number;
  stream_share: number;
}
export interface RunningCall {
  id: number;
  ts: number;
  account: string;
  model: string;
  platform: string;
  stream: boolean;
  phase: "waiting" | "upstream" | "streaming";
  age_ms: number;
  wait_ms: number;
  ttft_ms: number | null;
  tokens_out: number;
  retries: number;
  images: number;
  hands: boolean;
}
export interface RecentCall {
  ts: number;
  account: string;
  model: string;
  platform: string;
  status: string;
  detail: string;
  stream: boolean;
  wait_ms: number;
  ttft_ms: number;
  total_ms: number;
  prompt_tokens: number;
  completion_tokens: number;
  images: number;
  tools: number;
  hands: boolean;
  retries: number;
}
export interface HubStats {
  online: number;
  accounts_online: number;
  pending_calls: number;
  dropped_frames: number;
  flood_closes: number;
  slow_closes: number;
  /** Sockets closed before their hello: an address opening too many, an account with too many open (relay 0.30). */
  refused_connections?: number;
}
export interface UpstreamGate {
  active: number;
  waiting: number;
  limit: number;
}
export interface Live {
  time: number;
  gate: UpstreamGate;
  model_gates?: Record<string, UpstreamGate>;
  in_flight: { requests: number; accounts: number; limit: number };
  running: RunningCall[];
  hub: HubStats | null;
  minutes: LiveMinute[];
  last_10m: LiveSummary;
  last_hour: LiveSummary;
  recent: RecentCall[];
  since_start: { started_at: number; counts: Record<string, number> };
  models: string[];
  settings: { chat_concurrency: number; max_in_flight: number; upstream_timeout_s: number; chat_retries: number };
}

export interface UsageCell {
  requests: number;
  prompt_tokens: number;
  completion_tokens: number;
  cached_tokens: number;
  cost_cny: number;
  accounts: number;
}
export interface UsageDayRow {
  day: number;
  requests: number;
  prompt_tokens: number;
  completion_tokens: number;
  cached_tokens: number;
  cost_cny: number;
  active_accounts: number;
  models: Record<string, UsageCell>;
}
export interface UsageModel {
  model: string;
  kind: string;
  requests: number;
  prompt_tokens: number;
  completion_tokens: number;
  cached_tokens: number;
  cost_cny: number;
  days: number;
}
/** A turn people ran on a key of their own and sent up (POST /v1/turns), per provider and model. */
export interface OwnKeyUsage {
  provider: string;
  model: string;
  turns: number;
  accounts: number;
  prompt_tokens: number;
  completion_tokens: number;
  cached_tokens: number;
}
export interface Usage {
  generated_at: number;
  days: number;
  day_offset_h: number;
  rows: UsageDayRow[];
  models: UsageModel[];
  totals: { requests: number; prompt_tokens: number; completion_tokens: number; cached_tokens: number; cost_cny: number; active_days: number };
  own_keys: OwnKeyUsage[];
}
export interface DayHour {
  hour: number;
  requests: number;
  cost_cny: number;
  accounts: number;
  models: Record<string, { requests: number; prompt_tokens: number; completion_tokens: number; cost_cny: number }>;
  upstream_errors: number;
  budget_refused: number;
  content_rejected: number;
  sign_ins: number;
}
export interface CallsSummary {
  calls: number;
  by_status: Record<string, number>;
  hands: number;
  with_images: number;
  with_tools: number;
  p50_ttft_ms: number;
  p95_ttft_ms: number;
  p50_total_ms: number;
  p95_total_ms: number;
  p95_wait_ms: number;
  waited_share: number;
}
export interface Labelled {
  account_id: string;
  hint: string;
  identifier: string;
}
export interface DayView {
  day: number;
  end: number;
  day_offset_h: number;
  hours: DayHour[];
  platforms: { platform: string; requests: number; accounts: number; cost_cny: number; avg_prompt_tokens: number; avg_completion_tokens: number }[];
  calls: CallsSummary;
  latency: { hour: number; n: number; p50_ttft: number; p95_ttft: number; p50_total: number; p95_total: number; p95_wait: number }[];
  by_model_status: Record<string, Record<string, number>>;
  errors: { detail: string; n: number }[];
  content_rejected: { detail: string; n: number }[];
  top_accounts: (Labelled & { requests: number; charged: number; prompt_tokens: number; completion_tokens: number; cost_cny: number; platform: string; family: string })[];
}

export interface PlatformCalls {
  n: number;
  ok_share: number;
  error_share: number;
  refused: number;
  hands_share: number;
  images_share: number;
  tools_share: number;
  stream_share: number;
  avg_messages: number;
  p50_ttft_ms: number;
  p95_ttft_ms: number;
  p50_total_ms: number;
  p95_wait_ms: number;
}
export interface PlatformRow {
  platform: string;
  app: boolean;
  requests: number;
  accounts: number;
  requests_per_account: number;
  cost_cny: number;
  cost_per_account_cny: number;
  avg_prompt_tokens: number;
  avg_completion_tokens: number;
  versions: { version: string; requests: number }[];
  calls: PlatformCalls | null;
}
export interface Platforms {
  generated_at: number;
  days: number;
  platforms: PlatformRow[];
  accounts_by_last_client: { platform: string; accounts: number; disabled: number }[];
  multi_platform_accounts: number;
  accounts_with_requests: number;
  combinations: { platforms: string; accounts: number }[];
  devices: { kind: string; os: string; devices: number; seen_30d: number; screen: number; versions: { version: string; devices: number }[] }[];
  online: Record<string, number>;
  own_models: { provider: string; devices: number; accounts: number; models: { model: string; devices: number }[] }[];
  known_platforms: string[];
}

export interface Cohorts {
  generated_at: number;
  days: number;
  allowance_cny: number;
  pool: { limited: number; never_used: number; buckets: { used: string; accounts: number }[]; granted_cny: number; spent_cny: number };
  exhaustion: { accounts: number; median_days: number | null; p25_days: number | null; p75_days: number | null; buckets: { days: string; accounts: number }[] };
  after_exhaustion: { total: number; chatted_again: number; active_no_chat: number; gone: number; disabled: number; synced_assistant_after: number };
  own_key: {
    window_days: number;
    own_key_likely: number;
    both: number;
    cloud_only: number;
    app_open_no_model: number;
    synced_any: number;
    accounts: (Labelled & { synced_replies: number; devices: string })[];
  };
  retention: { week: number; signups: number; chat: (number | null)[]; any: (number | null)[] }[];
}

export interface Hands {
  generated_at: number;
  days: number;
  summary: { calls: number; hands: number; hands_share: number; hands_accounts: number; accounts_with_operable_device: number };
  days_series: { day: number; calls: number; hands: number; accounts: number; hands_accounts: number; platforms: Record<string, number> }[];
  platforms: { platform: string; calls: number; hands: number; ok: number; errors: number; with_images: number }[];
  tools: { tool: string; calls: number; hands: boolean; platforms: Record<string, number> }[];
  accounts: (Labelled & { turns: number; ok: number; first_ts: number; last_ts: number; platforms: string })[];
  devices: { kind: string; devices: number; screen: number; screen_seen_30d: number }[];
  samples: { turns: number; hands: number; by_platform: { platform: string; turns: number; hands: number; accounts: number }[] };
  hands_tools: string[];
  hands_prefixes: string[];
}

export interface QualityAccount extends Labelled {
  channel: string;
  contribute: boolean;
  disabled: boolean;
  created_at: number;
  platform: string;
  turns: number;
  trivial: number;
  short_replies: number;
  repeat_share: number;
  hands: number;
  with_tools: number;
  with_pictures: number;
  avg_user_chars: number;
  avg_reply_chars: number;
  avg_messages: number;
  bytes: number;
  first_ts: number;
  last_ts: number;
  platforms: string;
  score: number;
  tier: "high" | "medium" | "low";
}
export interface Quality {
  generated_at: number;
  days: number;
  coverage: { samples: number; described: number; backfill_done: boolean; share: number };
  period: {
    turns: number;
    accounts: number;
    trivial: number;
    trivial_share: number;
    short_replies: number;
    repeated_turns: number;
    repeated_share: number;
    repeated_messages: number;
    hands: number;
    with_tools: number;
    with_pictures: number;
    bytes: number;
    avg_user_chars: number;
    avg_reply_chars: number;
    avg_messages: number;
  };
  all_time: { turns: number; accounts: number; bytes: number; trivial: number };
  series: { day: number; turns: number; accounts: number; trivial: number; hands: number; with_tools: number; with_pictures: number; bytes: number }[];
  tiers: { tier: string; accounts: number; turns: number }[];
  top_accounts: QualityAccount[];
  low_accounts: QualityAccount[];
  scripted_accounts: QualityAccount[];
  top_repeats: { hash: string; turns: number; accounts: number; chars: number }[];
  by_platform: { platform: string; turns: number; accounts: number; trivial: number; hands: number; with_tools: number; with_pictures: number; avg_user_chars: number; bytes: number }[];
  scoring: { trivial_chars: number; short_reply_chars: number; full_depth_turns: number; high: string; low: string };
}

export interface Abuse {
  generated_at: number;
  days: number;
  summary: {
    requests: number;
    non_app_requests: number;
    non_app_request_share: number;
    non_app_cost_cny: number;
    non_app_cost_share: number;
    non_app_accounts: number;
    families: number;
  };
  families: {
    family: string;
    platform: string;
    app: boolean;
    requests: number;
    request_share: number;
    accounts: number;
    cost_cny: number;
    cost_share: number;
    avg_prompt_tokens: number;
    avg_completion_tokens: number;
    distinct_uas: number;
  }[];
  sign_ins: { family: string; sign_ins: number; accounts: number; app: boolean }[];
  accounts_by_last_client: { family: string; accounts: number; disabled: number; app: boolean }[];
  suspects: (Labelled & {
    channel: string;
    disabled: boolean;
    member: boolean;
    created_at: number;
    family: string;
    ua: string;
    requests: number;
    avg_prompt_tokens: number;
    cost_cny: number;
    last_ts: number;
  })[];
  shared_addresses: { ip: string; accounts: number; disabled: number; first_at: number; last_at: number }[];
  /** 0.28: whether the models answer nanoMuse clients only, and whom that turned away */
  apps_only: boolean;
  refused: { family: string; requests: number; accounts: number; last_ts: number }[];
}

// -- people ---------------------------------------------------------------------------------

export interface DeviceRow {
  id: string;
  name: string;
  kind: string;
  os: string;
  version?: string;
  online: boolean;
  last_seen: number;
  actions?: string[];
  llm_provider?: string;
  llm_model?: string;
}
export interface Account {
  id: string;
  channel: string;
  hint: string;
  created_at: number;
  granted: number;
  used: number;
  disabled: boolean;
  unlimited: boolean;
  invite_code: string;
  invited_by: string;
  invites: number;
  contribute: boolean;
  first_ip: string;
  last_ip: string;
  last_ua: string;
  last_seen_at: number;
  sync_enabled: number;
  used_today: number;
  requests: number;
  last_active_at: number;
  live_keys: number;
  device_count: number;
  identifier: string;
  has_password: boolean;
  locked: boolean;
  listed: boolean;
  member: boolean;
  review: boolean;
  spent_today_cny: number;
  spent_cny: number;
  grant_cny: number;
  left_cny: number;
  last_platform: string;
  last_version: string;
  devices: DeviceRow[];
}
export interface AccountsPage {
  accounts: Account[];
  settings: Settings;
}
export interface Invitee {
  id: string;
  hint: string;
  channel: string;
  created_at: number;
  disabled: boolean;
  first_ip: string;
  last_ip: string;
  last_seen_at: number | null;
  requests: number;
  spent_cny: number;
  settled: boolean;
}
export interface LedgerRow {
  id: number;
  ts: number;
  kind: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  charged: number;
  ip: string;
  ua: string;
  cost_cny: number;
  platform: string;
}
export interface AccountDetail {
  account: Account & {
    failed_logins: number;
    locked_until: number | null;
    invited: Invitee[];
    invited_total: number;
    inviter: { id: string; hint: string; channel?: string } | null;
    invite_earned_cny: number;
    samples: number;
  };
  addresses: { ip: string; n: number; first_seen: number; last_seen: number; platforms: string[] }[];
  ledger_total: number;
  events_total: number;
  spend: { today_cny: number; total_cny: number; grant_cny: number; left_cny: number; used_today: number; requests_total: number };
  usage: {
    today: { by_kind: KindRow[] };
    period: { days: number; by_kind: KindRow[]; by_model: ModelRow[]; by_day: { day: number; kind: string; requests: number; charged: number; cost_cny: number }[] };
    total: { by_kind: KindRow[] };
  };
  sessions: { prefix: string; device: string; via: string; created_at: number; last_used_at: number; revoked_at: number | null; ip: string; ua: string; platform: string; version: string }[];
  devices: DeviceRow[];
  recent: LedgerRow[];
  events: EventRow[];
  calls: { n: number; ok: number; errors: number; refused: number; hands: number; images: number; with_tools: number; avg_ttft_ms: number; avg_total_ms: number; avg_wait_ms: number; last_ts: number };
  demo: { visitor: DemoVisitor | null; visits: DemoVisit[]; visits_total: number } | null;
}
export interface Address {
  ip: string;
  accounts: { id: string; hint: string; channel: string; created_at: number; n: number; last_seen: number }[];
  place: { country: string; code: string; province: string; city: string; isp: string; local: boolean; text: string } | null;
}
export interface Sample {
  id: string;
  account_id: string;
  ts: number;
  model: string;
  request: { role: string; content: unknown }[];
  response: string;
  prompt_tokens: number;
  completion_tokens: number;
  meta: { ua?: string; lang?: string; ip?: string };
  platform: string;
  hint?: string;
}

export interface Leader {
  id: string;
  hint: string;
  identifier: string;
  channel: string;
  created_at: number;
  disabled: boolean;
  first_ip: string;
  last_ip: string;
  invites: number;
  invited: number;
  invited_active: number;
  invited_settled: number;
  invited_pending: number;
  invited_same_ip: number;
  invited_spent_cny: number;
  earned_cny: number;
  first_invite_at: number;
  last_invite_at: number;
  invitees: Invitee[];
}
export interface Invites {
  generated_at: number;
  funnel: { with_code: number; inviters: number; invited: number; contribute_bonuses: number };
  leaders: Leader[];
}
export interface PlaceCell {
  country: string;
  code: string;
  province: string;
  n: number;
  ips: number;
}
export interface Places {
  days: number;
  geo: Geo;
  accounts: PlaceCell[];
  requests: PlaceCell[];
  signins: PlaceCell[];
  new_accounts: PlaceCell[];
  demo_visitors: PlaceCell[] | null;
}

export interface DemoVisitor {
  id: string;
  hint: string;
  channel: string;
  created: boolean;
  signins: number;
  sessions: number;
  first_seen: number;
  last_seen: number;
  last_ua: string;
  last_ip: string;
  first_ip: string;
}
export interface DemoVisit {
  id: string;
  started: number;
  ended: number | null;
  reason: string;
  visitor: string;
  account_id?: string;
  hint?: string;
  byok: boolean;
  ua: string;
  ip: string;
  requests?: number;
  tokens?: number;
  model?: string;
}
export interface Demo {
  available: boolean;
  signin_required?: boolean;
  visitors?: DemoVisitor[];
  visitors_total?: number;
  visits?: DemoVisit[];
  visits_total?: number;
  active?: DemoVisit[];
  days?: number;
}

export interface DataView {
  generated_at: number;
  default_on: boolean;
  keeps: { kept: string[]; not_kept: string[] };
  accounts: { total: number; on: number; off: number; share: number; turned_off_ever: number; with_samples: number };
  /** `samples` counts the calls kept (one row each); `turns` the questions among them — the calls that opened one
   *  (0.31); `turns_pending` the rows the backfill has not read yet, counted in neither. */
  totals: { samples: number; turns: number; turns_pending: number; prompt_tokens: number; completion_tokens: number };
  period: { days: number; samples: number; turns: number; accounts: number; prompt_tokens: number; completion_tokens: number };
  days: { day: number; samples: number; turns: number; accounts: number; prompt_tokens: number; completion_tokens: number; turned_on: number; turned_off: number; default_on: number; deleted: number }[];
  by_model: { model: string; samples: number; turns: number; tokens: number }[];
  by_platform: { platform: string; samples: number; turns: number }[];
  /** 0.31: who started the kept turns (person, schedule, feed, goal, hub; "" before the apps said) and the key they ran on (cloud, own). */
  by_run: { run: string; samples: number; turns: number }[];
  by_source: { source: string; samples: number; turns: number }[];
  by_account: { account_id: string; hint: string; channel: string; contribute: boolean; created_at: number; samples: number; turns: number; prompt_tokens: number; completion_tokens: number; first_ts: number; last_ts: number; models: string[] }[];
  recent: Sample[];
}
/** What the apps report around turns (0.31): GET /v1/admin/client-events/summary. Codes and counts, never a message. */
export interface ClientEventsSummary {
  period: { days: number; since: number };
  total: number;
  accounts: number;
  kinds: Record<string, number>;
  days: ({ day: number } & Record<string, number>)[];
  /** per kind, per data key, the split of its codes: facets["sentinel.decision"]["decision"] = { allow: n, ask: n, deny: n } */
  facets: Record<string, Record<string, Record<string, number>>>;
}
/** The deletions ledger (0.31): GET /v1/admin/deletions. */
export interface Deletions {
  deletions: { subject: string; ts: number; scope: string }[];
}
/** The record (0.29): every turn in full, its pictures as files — GET /v1/admin/record. */
export interface RecordView {
  on: boolean;
  keep_days: number;
  media_dir: string;
  media_cap_bytes: number;
  /** `n` is the calls (one row each); `questions` the turns the person asked (0.31: the calls that opened one) */
  totals: { n: number; questions: number; accounts: number; own: number; partial: number; media: number; media_bytes: number; files: number; store_bytes: number };
  period: { days: number; n: number; questions: number; accounts: number; own: number; partial: number; media: number; media_bytes: number };
  /** the record counted by questions over the period: how many, how many calls each took (bucketed), how many carried a
   *  picture or ran the hands, and how many calls the backfill has not yet assigned to a question */
  questions: { n: number; pending: number; with_media: number; with_hands: number; calls_per_question: Record<string, number>; calls_mean: number };
  days: { day: number; turns: number; questions: number; accounts: number; media: number; media_bytes: number }[];
}

/** A message as the record keeps it: pictures, clips and audio are `blob:sha256:…` references (GET /v1/admin/blobs/{sha256}). */
export interface TurnMessage {
  role: string;
  content?: unknown;
  tool_calls?: { id?: string; type?: string; function?: { name?: string; arguments?: string } }[];
  tool_call_id?: string;
  reasoning_content?: string;
  name?: string;
  /** the laid-out view cut this message's text (turnview.TEXT_MAX); the whole call has it */
  truncated?: boolean;
}
/** One model call inside a question, as the laid-out view carries it. */
export interface TurnStep {
  call: { id: string; ts: number; model: string; step?: number; status: string; source: string; platform: string; prompt_tokens: number; completion_tokens: number; trajectory?: string; trajectory_step?: number; run?: string };
  /** messages in this call's request (the whole history the model saw) */
  messages: number;
  /** what the model answered: its words, or the tools it called */
  reply: TurnMessage;
  /** what came back before the next call: tool results, the hands' screenshots, a message the person added */
  then: TurnMessage[];
}
/** One question with every model call it took — GET /v1/admin/record/turns (0.31). */
export interface TurnGroup {
  key: string;
  account_id: string;
  hint: string;
  ts0: number;
  ts1: number;
  calls: number;
  conversation: string;
  device: string;
  platform: string;
  run: string;
  turn: number;
  source: string;
  sources: string[];
  models: string[];
  script: string;
  trajectory: string;
  prompt_tokens: number;
  completion_tokens: number;
  /** pictures and clips the calls carried, the history included (the filter and the figures use it) */
  media: number;
  partial: number;
  status: string;
  ended: string;
  /** the person's message that opened the question (null when the request had none) */
  person: TurnMessage | null;
  steps: TurnStep[];
  /** the reply the person saw: the last call's words */
  reply: string;
  /** the tools called, in order */
  tools: string[];
}
export interface TurnGroups {
  turns: TurnGroup[];
  pending: number;
  total: number;
}
/** One call of the record in full — GET /v1/admin/turns/{id}. */
export interface TurnFull {
  id: string;
  account_id: string;
  hint: string;
  ts: number;
  model: string;
  platform: string;
  device: string;
  conversation: string;
  source: string;
  status: string;
  request: { model?: string; messages?: TurnMessage[]; tools?: unknown[] } & Record<string, unknown>;
  response: { message?: TurnMessage; usage?: Record<string, number>; finish_reason?: string };
  prompt_tokens: number;
  completion_tokens: number;
  media: number;
  media_bytes: number;
  meta: Record<string, unknown>;
  run?: string;
  turn?: number;
  step?: number;
  trajectory?: string;
  trajectory_step?: number;
  script?: string;
  turn_key?: string;
  turn_start?: boolean;
}
export interface Sync {
  accounts_enabled: number;
  accounts_disabled: number;
  accounts_with_data: number;
  conversations: number;
  messages: number;
  bytes: number;
  limits: { messages: number; text_bytes: number; conversations: number };
}

export interface Health {
  ok: boolean;
  version: string;
  time: number;
  in_flight: { requests: number; accounts: number; limit: number };
  chat_upstream: UpstreamGate & { retries: number };
  model_gates?: Record<string, UpstreamGate>;
  hub: HubStats | null;
  last_hour: { requests: number; upstream_errors: number; content_rejected: number; budget_refused: number; sign_ins: number; sign_in_failures: number };
  db: { size_bytes: number; writable: boolean };
  upstream_key: boolean;
  alerts: { message: string; hint: string; account_id?: string; kind?: string }[];
  problems: string[];
}

export interface Traffic {
  available: boolean;
  since?: string;
  updated_at?: number;
  days?: { day: string; requests: number; pages: number; visitors: number; bots: number; downloads: number; bytes: number }[];
  pages?: { name: string; hits: number }[];
  referrers?: { name: string; hits: number }[];
  downloads?: { name: string; hits: number; bytes: number }[];
  github?: { days: { day: string; stars: number; downloads: number }[]; day?: string; stars?: number; forks?: number; watchers?: number; downloads?: number; assets?: Record<string, number> };
}
export interface GitHub {
  status: { enabled: boolean; repo: string; token: boolean; last_run: number | null; last_ok: number | null; error: string; running: boolean; interval_s: number };
  days: {
    day: number;
    snapshot: boolean;
    stars: number | null;
    new_stars: number | null;
    forks: number | null;
    new_forks: number | null;
    watchers: number | null;
    new_watchers: number | null;
    issues: number | null;
    new_issues: number | null;
    downloads: number | null;
    new_downloads: number | null;
  }[];
  latest: {
    day: number | null;
    stars: number | null;
    forks: number | null;
    watchers: number | null;
    issues: number | null;
    downloads: number | null;
    platforms: Record<string, number>;
    assets: { name: string; downloads: number; platform: string }[];
    releases: { tag: string; downloads: number }[];
  };
}
export interface Catalog {
  enabled: boolean;
  probe: boolean;
  fetched_at: number | null;
  error: string;
  probing: boolean;
  models: { id: string; kind: string; vision: boolean; verified: boolean }[];
  unusable: { id: string; note: string; checked_at: number }[];
  pending: number;
}
export interface Metric {
  id: string;
  title: string;
  title_zh: string;
  how: string;
  how_zh: string;
  shape: string;
  columns: { key: string; label: string; label_zh: string; kind: string }[];
  chart: string[];
  rows: Record<string, unknown>[];
}
export interface Stats {
  generated_at: number;
  days: number;
  since: number;
  metrics: Metric[];
}
export interface Rule {
  id: number;
  threshold: number;
  action: string;
  enabled: boolean;
  note: string;
  created_at: number;
  last_fired_at: number | null;
  fired_accounts: number | null;
}
export interface AuditRow {
  id: number;
  ts: number;
  actor: string;
  ip: string;
  action: string;
  target: string;
  detail: string;
}
export interface Controls {
  switches: Record<string, Switch>;
  rules: Rule[];
  accounts_total: number;
  next_threshold: number | null;
  notify_configured: boolean;
  admin_email_set: boolean;
  audit: AuditRow[];
}
export interface NudgesPolicy {
  version: number;
  star: {
    enabled: boolean;
    url: string;
    moments: { signed_in: boolean; tasks: number[]; new_look: boolean; exhausted: boolean; days_used: number[]; goal_done: boolean };
    cooldown_days: number;
    max_asks: number;
    text: string;
    text_zh: string;
  };
}
export interface Nudges {
  nudges: NudgesPolicy;
  defaults: NudgesPolicy;
  stored: boolean;
  updated_at: number | null;
}
