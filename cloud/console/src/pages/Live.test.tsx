import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { LangContext } from "../lib/i18n";
import { en, zh } from "../lib/locales";
import type { Health, Live, LiveSummary } from "../lib/types";
import { HealthPage } from "./Health";
import { LivePage } from "./Live";

let response: Live | Health;
vi.mock("../lib/hooks", () => ({ useData: () => ({ data: response, at: 1000 }), useNow: () => 1 }));
vi.mock("../App", () => ({ errorText: () => "" }));

const summary: LiveSummary = {
  requests: 0, ok: 0, errors: 0, refused: 0, by_status: {}, accounts: 0,
  p50_ttft_ms: 0, p95_ttft_ms: 0, p50_total_ms: 0, p95_total_ms: 0, p50_wait_ms: 0, p95_wait_ms: 0,
  waited_share: 0, tokens_out: 0, tokens_out_per_s: 0, hands: 0, with_images: 0, stream_share: 0,
};
const lanes = {
  "deepseek-v4.1-flash-1017": { active: 60, waiting: 3, limit: 60 },
  "qwen3.5-397b-a17b": { active: 0, waiting: 0, limit: 60 },
};
const live: Live = {
  time: 1, gate: { active: 60, waiting: 3, limit: 120 }, in_flight: { requests: 63, accounts: 32, limit: 2 },
  models: Object.keys(lanes), running: [], minutes: [], recent: [], hub: null, last_10m: summary, last_hour: summary,
  since_start: { started_at: 1, counts: {} }, settings: { chat_concurrency: 120, max_in_flight: 2, upstream_timeout_s: 60, chat_retries: 1 },
};
function renderLive(changes: Partial<Live>) {
  response = { ...live, ...changes };
  return renderToStaticMarkup(<LangContext.Provider value={{ lang: "en", setLang: () => {} }}><LivePage /></LangContext.Provider>);
}

describe("model concurrency", () => {
  it("shows each pool's occupancy and queue and detects a full pool even when half of the combined slots are idle", () => {
    const html = renderLive({ model_gates: lanes });
    expect(html).toContain(en.lv.verdictSaturated);
    expect(html).toContain(en.lv.modelGates);
    expect(html).toMatch(/deepseek-v4\.1-flash-1017[\s\S]*?60 \/ 60 in use[\s\S]*?3 queued<\/span>[\s\S]*?<\/li>/);
    expect(html).toMatch(/qwen3\.5-397b-a17b[\s\S]*?0 \/ 60 in use[\s\S]*?0 queued<\/span>/);
    expect(html).not.toContain(en.lv.gateSub(120));
    expect(html).not.toContain(en.lv.concurrency + "</span>");
  });

  it("marks a 75%-occupied model busy even with an idle sibling, and still considers recent waits", () => {
    const model_gates = { model1: { active: 45, waiting: 0, limit: 60 }, model2: { active: 0, waiting: 0, limit: 60 } };
    expect(renderLive({ model_gates, gate: { active: 45, limit: 120, waiting: 0 } })).toContain(en.lv.verdictBusy);
    expect(renderLive({ model_gates, last_10m: { ...summary, p95_wait_ms: 2500 } })).toContain(en.lv.verdictSaturated);
  });

  it.each([undefined, {}])("keeps the single-pool layout for legacy and unconfigured relays", (model_gates) => {
    const html = renderLive({ model_gates, gate: { active: 6, waiting: 0, limit: 8 } });
    expect(html).toContain(en.lv.gateSub(8));
    expect(html).toContain(en.lv.activeOf(6, 8));
    expect(html).toContain(en.lv.verdictBusy);
    expect(html).not.toContain(en.lv.modelGates);
  });

  it("shows both pools on the Chinese health page while retaining its configured retry count", () => {
    response = {
      time: 1, version: "test", ok: true, problems: [], alerts: [], in_flight: live.in_flight,
      chat_upstream: { ...live.gate, retries: 2 }, model_gates: lanes, hub: null, upstream_key: true, db: { size_bytes: 0, writable: true },
      last_hour: { requests: 0, upstream_errors: 0, content_rejected: 0, budget_refused: 0, sign_ins: 0, sign_in_failures: 0 },
    };
    const html = renderToStaticMarkup(<HealthPage />);
    expect(html).toContain(zh.lv.modelGates);
    expect(html).toContain(zh.lv.activeOf(60, 60));
    expect(html).toContain(zh.lv.queued(0));
    expect(html).toContain(zh.g.retries + " 2");
  });
});
