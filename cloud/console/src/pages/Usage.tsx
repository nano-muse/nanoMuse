/** Usage: the day × model matrix for the period, how much of the prompts the provider's cache
 *  served (hosted models, and the turns people ran on keys of their own), and one day in full
 *  (hours, platforms, outcomes and latency, error reasons, the accounts that cost most); the
 *  price table. */

import { useMemo } from "react";
import type { PageProps } from "../App";
import { compact, fmt, money, moneyN, ms, pct, siteDay, siteDayStamp, siteWeekday } from "../lib/format";
import { useData, useNow } from "../lib/hooks";
import { nameOf, useT, useZh } from "../lib/i18n";
import { useRoute } from "../lib/router";
import type { DayView, Overview, Usage as UsageT } from "../lib/types";
import { Bars, Legend, Lines, Ranks, heatStyle, modelColor, platformColor, statusColor } from "../ui/charts";
import { Btn, Chips, DataTable, Grid, Kpi, Kpis, Note, Panel, Seg, cx, type Col } from "../ui/primitives";
import { PlatformPill, Who } from "../ui/who";
import { Loaded } from "./common";

type Metric = "requests" | "cost_cny" | "prompt_tokens" | "completion_tokens" | "cached_tokens" | "accounts";
const METRICS: Metric[] = ["requests", "cost_cny", "prompt_tokens", "completion_tokens", "cached_tokens", "accounts"];
/** The cached share of the input: 0 when nothing was prompted. */
const share = (cached: number, prompt: number) => (prompt > 0 ? cached / prompt : 0);
const fmtOf = (m: Metric) => (m === "cost_cny" ? (v: number) => money(v) : m === "requests" || m === "accounts" ? fmt : compact);

export function Usage({ days }: PageProps) {
  const T = useT();
  const zh = useZh();
  const route = useRoute();
  const metric = (METRICS.includes(route.params.get("m") as Metric) ? route.params.get("m") : "requests") as Metric;
  const day = Number(route.params.get("day") || 0);
  const q = useData<UsageT>(`/v1/admin/analytics/usage?days=${days}`, { poll: 120_000 });
  const ov = useData<Overview>(`/v1/admin/overview?days=7`, { maxAge: 300_000 });
  if (day) return <DayPage day={day} onBack={() => route.set({ day: null })} onDay={(d) => route.set({ day: d })} />;
  return (
    <Loaded q={q}>
      {(d) => {
        const models = d.models;
        const f = fmtOf(metric);
        const cell = (row: UsageT["rows"][number], m: string): number => Number(row.models[m]?.[metric] || 0);
        const rowTotal = (row: UsageT["rows"][number]): number => (metric === "accounts" ? row.active_accounts : Number(row[metric as "requests"] || 0));
        const max = Math.max(1e-9, ...d.rows.flatMap((r) => models.map((m) => cell(r, m.model))));
        const costPerReq = d.totals.requests ? d.totals.cost_cny / d.totals.requests : 0;
        const stacked = models.map((m) => ({ name: m.model, values: d.rows.map((r) => cell(r, m.model)), color: modelColor(m.model) }));
        return (
          <>
            <Kpis>
              <Kpi label={T.g.requests} value={fmt(d.totals.requests)} sub={`${d.totals.active_days} / ${d.days} ${T.us.activeDays}`} />
              <Kpi label={T.g.cost} value={money(d.totals.cost_cny)} sub={`${T.us.costPerReq} ${money(costPerReq, 4)}`} />
              <Kpi label={T.g.tokensIn} value={compact(d.totals.prompt_tokens)} sub={`${T.us.avgIn} ${fmt(d.totals.requests ? d.totals.prompt_tokens / d.totals.requests : 0)}`} />
              <Kpi label={T.g.tokensOut} value={compact(d.totals.completion_tokens)} sub={`${T.us.avgOut} ${fmt(d.totals.requests ? d.totals.completion_tokens / d.totals.requests : 0)}`} />
              <Kpi label={<span title={T.us.cachedHint}>{T.us.cached}</span>} value={d.totals.prompt_tokens ? pct(share(d.totals.cached_tokens, d.totals.prompt_tokens), 1) : "·"} sub={`${compact(d.totals.cached_tokens)} ${T.us.cachedOf(compact(d.totals.prompt_tokens))}`} tone={d.totals.prompt_tokens > 100_000 && share(d.totals.cached_tokens, d.totals.prompt_tokens) < 0.05 ? "warn" : ""} />
              <Kpi label={T.g.model} value={models.length} sub={models.map((m) => m.model).slice(0, 3).join(", ")} small />
              <Kpi label={T.g.perDay} value={money(d.totals.cost_cny / Math.max(1, d.totals.active_days))} sub={`${fmt(d.totals.requests / Math.max(1, d.totals.active_days))} ${T.g.requests}`} />
            </Kpis>
            <Panel title={T.us.title(days)} sub={T.us.matrixHint}>
              <Bars series={stacked} labels={d.rows.map((r) => siteDay(r.day, d.day_offset_h).slice(5))} titles={d.rows.map((r) => siteDay(r.day, d.day_offset_h))} format={f} height={170} onPick={(i) => route.set({ day: d.rows[i].day })} />
              <Legend className="mt-2" items={models.map((m) => ({ name: <code>{m.model}</code>, color: modelColor(m.model), value: f(Number(m[metric === "accounts" ? "requests" : metric])) }))} />
            </Panel>
            <Panel title={T.us.matrix} right={<Chips options={METRICS.map((m) => ({ id: m, label: T.us.metric[m] }))} value={metric} onChange={(m) => route.set({ m }, true)} />} pad={false}>
              <div className="scroll-x" style={{ maxHeight: 640, overflowY: "auto" }}>
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>{T.g.day}</th>
                      <th className="num">{T.g.total}</th>
                      {models.map((m) => (
                        <th key={m.model} className="num">
                          <span className="inline-flex items-center gap-1.5">
                            <span className="inline-block h-2 w-2 rounded-sm" style={{ background: modelColor(m.model) }} />
                            <code>{m.model}</code>
                          </span>
                        </th>
                      ))}
                      <th className="num hide-sm">{T.us.activeAccounts}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...d.rows].reverse().map((r) => (
                      <tr key={r.day} className="tap" onClick={() => route.set({ day: r.day })}>
                        <td>
                          {siteDay(r.day, d.day_offset_h)} <span className="hint">{siteWeekday(r.day, d.day_offset_h, zh)}</span>
                        </td>
                        <td className="num font-medium">{f(rowTotal(r))}</td>
                        {models.map((m) => {
                          const v = cell(r, m.model);
                          return (
                            <td key={m.model} className="num">
                              {v ? (
                                <span className="heat" style={heatStyle(v, max, m.model === models[0]?.model ? "37, 99, 235" : "124, 58, 237")}>
                                  {f(v)}
                                </span>
                              ) : (
                                <span className="text-ink-3">·</span>
                              )}
                            </td>
                          );
                        })}
                        <td className="num hide-sm">{fmt(r.active_accounts)}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td className="font-medium">{T.g.total}</td>
                      <td className="num font-medium">{metric === "accounts" ? "·" : f(Number(d.totals[metric as "requests"]))}</td>
                      {models.map((m) => (
                        <td key={m.model} className="num font-medium">
                          {metric === "accounts" ? "·" : f(Number(m[metric as "requests"]))}
                        </td>
                      ))}
                      <td className="hide-sm" />
                    </tr>
                  </tfoot>
                </table>
              </div>
            </Panel>
            <Grid cols={2}>
              <Panel title={T.us.models}>
                <DataTable
                  rows={models}
                  rowKey={(m) => m.model}
                  defaultSort="cost_cny"
                  columns={[
                    { key: "model", label: T.g.model, render: (m) => <code>{m.model}</code> },
                    { key: "kind", label: T.g.kind, render: (m) => nameOf(T.kinds, m.kind) },
                    { key: "requests", label: T.g.requests, num: true, render: (m) => fmt(m.requests) },
                    { key: "share", label: T.us.reqShare, num: true, value: (m) => m.requests, render: (m) => pct(d.totals.requests ? m.requests / d.totals.requests : 0) },
                    { key: "cost_cny", label: T.g.cost, num: true, render: (m) => money(m.cost_cny) },
                    { key: "cshare", label: T.us.costShare, num: true, value: (m) => m.cost_cny, render: (m) => pct(d.totals.cost_cny ? m.cost_cny / d.totals.cost_cny : 0) },
                    { key: "per", label: T.us.costPerReq, num: true, value: (m) => (m.requests ? m.cost_cny / m.requests : 0), render: (m) => money(m.requests ? m.cost_cny / m.requests : 0, 4) },
                    { key: "prompt_tokens", label: T.us.avgIn, num: true, value: (m) => (m.requests ? m.prompt_tokens / m.requests : 0), render: (m) => fmt(m.requests ? m.prompt_tokens / m.requests : 0) },
                    { key: "completion_tokens", label: T.us.avgOut, num: true, value: (m) => (m.requests ? m.completion_tokens / m.requests : 0), render: (m) => fmt(m.requests ? m.completion_tokens / m.requests : 0) },
                    { key: "cached", label: T.us.cachedShare, num: true, value: (m) => share(m.cached_tokens, m.prompt_tokens), render: (m) => (m.prompt_tokens ? pct(share(m.cached_tokens, m.prompt_tokens), 1) : "·") },
                    { key: "days", label: T.us.activeDays, num: true, hideSm: true },
                  ]}
                />
              </Panel>
              <Panel title={T.us.prices}>{ov.data ? <Prices s={ov.data.settings} /> : <div className="hint py-4 text-center">{T.g.loading}</div>}</Panel>
            </Grid>
            <Panel title={T.us.ownKeys} sub={T.us.ownKeysHint} pad={d.own_keys.length > 0 ? false : undefined}>
              {d.own_keys.length ? (
                <DataTable
                  rows={d.own_keys}
                  rowKey={(o) => `${o.provider}/${o.model}`}
                  defaultSort="turns"
                  columns={[
                    { key: "provider", label: T.us.provider, render: (o) => <code>{o.provider || T.g.unknown}</code> },
                    { key: "model", label: T.g.model, render: (o) => <code>{o.model}</code> },
                    { key: "turns", label: T.us.turns, num: true, render: (o) => fmt(o.turns) },
                    { key: "accounts", label: T.g.accounts, num: true, render: (o) => fmt(o.accounts) },
                    { key: "prompt_tokens", label: T.us.avgIn, num: true, value: (o) => (o.turns ? o.prompt_tokens / o.turns : 0), render: (o) => fmt(o.turns ? o.prompt_tokens / o.turns : 0) },
                    { key: "completion_tokens", label: T.us.avgOut, num: true, value: (o) => (o.turns ? o.completion_tokens / o.turns : 0), render: (o) => fmt(o.turns ? o.completion_tokens / o.turns : 0) },
                    { key: "cached", label: T.us.cachedShare, num: true, value: (o) => share(o.cached_tokens, o.prompt_tokens), render: (o) => (o.prompt_tokens ? pct(share(o.cached_tokens, o.prompt_tokens), 1) : "·") },
                  ]}
                />
              ) : (
                <Note>{T.us.ownKeysNone}</Note>
              )}
            </Panel>
          </>
        );
      }}
    </Loaded>
  );
}

function Prices({ s }: { s: Overview["settings"] }) {
  const T = useT();
  const rows = (s.models || []).map((m) => ({ model: m, kind: s.model_kinds[m] || "", p: s.prices[m], lanes: s.model_lanes[m] || [], rec: s.recommended_for[m] || [] }));
  return (
    <div className="scroll-x">
      <table className="tbl">
        <thead>
          <tr>
            <th>{T.g.model}</th>
            <th>{T.g.kind}</th>
            <th className="num">{T.us.priceIn}</th>
            <th className="num">{T.us.priceOut}</th>
            <th className="num hide-sm">{T.us.priceCached}</th>
            <th className="num hide-sm">{T.us.pricePerImage}</th>
            <th className="num hide-sm">{T.us.pricePerSecond}</th>
            <th className="hide-sm">{T.us.lanes}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.model}>
              <td>
                <code>{r.model}</code>
              </td>
              <td>{nameOf(T.kinds, r.kind)}</td>
              <td className="num">
                {r.p ? `¥${moneyN(r.p.per_m_input)}` : "·"}
                {r.p && r.p.per_m_input_idle && r.p.per_m_input_idle !== r.p.per_m_input ? <span className="hint"> / {T.us.priceIdle} ¥{moneyN(r.p.per_m_input_idle)}</span> : null}
              </td>
              <td className="num">
                {r.p ? `¥${moneyN(r.p.per_m_output)}` : "·"}
                {r.p && r.p.per_m_output_idle && r.p.per_m_output_idle !== r.p.per_m_output ? <span className="hint"> / {T.us.priceIdle} ¥{moneyN(r.p.per_m_output_idle)}</span> : null}
              </td>
              <td className="num hide-sm">{r.p?.per_m_cached_input ? `¥${moneyN(r.p.per_m_cached_input)}` : "·"}</td>
              <td className="num hide-sm">{r.p?.per_image ? `¥${moneyN(r.p.per_image)}` : "·"}</td>
              <td className="num hide-sm">{r.p?.per_second ? `¥${moneyN(r.p.per_second)}` : Object.keys(r.p?.per_second_res || {}).length ? Object.entries(r.p!.per_second_res).map(([k, v]) => `${k} ¥${moneyN(v)}`).join(" · ") : "·"}</td>
              <td className="hide-sm">
                <span className="hint">{[...r.lanes, ...r.rec.map((x) => `→ ${x}`)].join(" · ")}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DayPage({ day, onBack, onDay }: { day: number; onBack: () => void; onDay: (d: number) => void }) {
  const T = useT();
  const zh = useZh();
  const q = useData<DayView>(`/v1/admin/analytics/day?day=${day}`, { poll: 120_000 });
  const route = useRoute();
  const hourMetric = (route.params.get("hm") === "cost" ? "cost" : "requests") as "cost" | "requests";
  const today = useNow(60_000);
  const models = useMemo(() => {
    if (!q.data) return [];
    const set = new Map<string, number>();
    for (const h of q.data.hours) for (const [m, v] of Object.entries(h.models)) set.set(m, (set.get(m) || 0) + v.requests);
    return [...set.entries()].sort((a, b) => b[1] - a[1]).map(([m]) => m);
  }, [q.data]);
  return (
    <Loaded q={q}>
      {(d) => {
        const total = d.hours.reduce((a, h) => a + h.requests, 0);
        const cost = d.hours.reduce((a, h) => a + h.cost_cny, 0);
        const labels = d.hours.map((h) => `${String(h.hour).padStart(2, "0")}`);
        const stacked = models.map((m) => ({ name: m, values: d.hours.map((h) => (hourMetric === "cost" ? Number(h.models[m]?.cost_cny || 0) : Number(h.models[m]?.requests || 0))), color: modelColor(m) }));
        const c = d.calls;
        const statuses = Object.keys(c.by_status).sort((a, b) => c.by_status[b] - c.by_status[a]);
        const topCols: Col<DayView["top_accounts"][number]>[] = [
          { key: "who", label: T.g.account, sortable: false, render: (a) => <Who id={a.account_id} hint={a.hint} identifier={a.identifier} /> },
          { key: "platform", label: T.g.platform, render: (a) => <PlatformPill platform={a.platform} /> },
          { key: "family", label: T.us.family, hideSm: true, render: (a) => <code>{a.family}</code> },
          { key: "requests", label: T.g.requests, num: true, render: (a) => fmt(a.requests) },
          { key: "cost_cny", label: T.g.cost, num: true, render: (a) => money(a.cost_cny) },
          { key: "prompt_tokens", label: T.g.tokensIn, num: true, hideSm: true, render: (a) => compact(a.prompt_tokens) },
          { key: "completion_tokens", label: T.g.tokensOut, num: true, hideSm: true, render: (a) => compact(a.completion_tokens) },
        ];
        return (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Btn size="sm" onClick={onBack}>
                ← {T.us.back}
              </Btn>
              <Btn size="sm" onClick={() => onDay(d.day - 86400)}>
                ‹ {T.us.prev}
              </Btn>
              <Btn size="sm" onClick={() => onDay(d.day + 86400)} disabled={d.day + 86400 > today}>
                {T.us.next} ›
              </Btn>
              <input type="date" className="inp" value={siteDay(d.day, d.day_offset_h)} max={siteDay(today, d.day_offset_h)} onChange={(e) => e.target.value && onDay(siteDayStamp(e.target.value, d.day_offset_h))} title={T.us.pickDay} />
              <h2 className="m-0 text-[15px] font-semibold">
                {T.us.dayTitle(siteDay(d.day, d.day_offset_h))} <span className="hint font-normal">{siteWeekday(d.day, d.day_offset_h, zh)}</span>
              </h2>
            </div>
            <Kpis>
              <Kpi label={T.g.requests} value={fmt(total)} sub={`${T.us.activeAccounts} ${fmt(Math.max(0, ...d.hours.map((h) => h.accounts)))} (${T.g.hour} max)`} />
              <Kpi label={T.g.cost} value={money(cost)} sub={`${T.us.costPerReq} ${money(total ? cost / total : 0, 4)}`} />
              <Kpi label={T.us.calls} value={fmt(c.calls)} sub={statuses.slice(0, 3).map((s) => `${nameOf(T.statuses, s)} ${fmt(c.by_status[s])}`).join(" · ")} />
              <Kpi label={T.lv.p50ttft} value={c.calls ? ms(c.p50_ttft_ms) : "·"} sub={c.calls ? `${T.g.p95} ${ms(c.p95_ttft_ms)}` : ""} />
              <Kpi label={T.lv.p95wait} value={c.calls ? ms(c.p95_wait_ms) : "·"} sub={c.calls ? `${T.us.waited} ${pct(c.waited_share, 1)}` : ""} tone={c.waited_share > 0.25 ? "bad" : c.waited_share > 0.05 ? "warn" : ""} />
              <Kpi label={T.g.hands} value={fmt(c.hands)} sub={`${T.g.images} ${fmt(c.with_images)} · ${T.g.tools} ${fmt(c.with_tools)}`} />
            </Kpis>
            <Panel title={T.us.hours} sub={T.us.hoursHint} right={<Seg options={[{ id: "requests", label: T.g.requests }, { id: "cost", label: T.g.cost }]} value={hourMetric} onChange={(v) => route.set({ hm: v === "cost" ? "cost" : null }, true)} />}>
              <Bars series={stacked} labels={labels} titles={d.hours.map((h) => `${siteDay(d.day, d.day_offset_h)} ${labels[h.hour]}:00 · ${fmt(h.accounts)} ${T.g.accounts}`)} format={hourMetric === "cost" ? (v) => money(v) : fmt} height={170} lines={[
                { name: T.ov.upstreamErrors, values: d.hours.map((h) => h.upstream_errors), color: "var(--bad)" },
                { name: T.ov.budgetRefusals, values: d.hours.map((h) => h.budget_refused), color: "var(--violet)" },
              ]} />
              <Legend className="mt-2" items={[...models.map((m) => ({ name: <code>{m}</code>, color: modelColor(m) })), { name: T.ov.upstreamErrors, color: "var(--bad)" }, { name: T.ov.budgetRefusals, color: "var(--violet)" }]} />
            </Panel>
            <Grid cols={2}>
              <Panel title={T.us.byPlatform}>
                <DataTable
                  rows={d.platforms}
                  rowKey={(p) => p.platform}
                  defaultSort="requests"
                  columns={[
                    { key: "platform", label: T.g.platform, render: (p) => <PlatformPill platform={p.platform} /> },
                    { key: "requests", label: T.g.requests, num: true, render: (p) => fmt(p.requests) },
                    { key: "share", label: T.g.share, num: true, value: (p) => p.requests, render: (p) => pct(total ? p.requests / total : 0) },
                    { key: "accounts", label: T.g.accounts, num: true, render: (p) => fmt(p.accounts) },
                    { key: "cost_cny", label: T.g.cost, num: true, render: (p) => money(p.cost_cny) },
                    { key: "avg_prompt_tokens", label: T.us.avgIn, num: true, hideSm: true, render: (p) => fmt(p.avg_prompt_tokens) },
                    { key: "avg_completion_tokens", label: T.us.avgOut, num: true, hideSm: true, render: (p) => fmt(p.avg_completion_tokens) },
                  ]}
                />
                <div className="mt-3 flex h-2 w-full overflow-hidden rounded-full bg-fill">
                  {d.platforms.map((p) => (
                    <span key={p.platform} style={{ width: `${total ? (100 * p.requests) / total : 0}%`, background: platformColor(p.platform) }} title={`${nameOf(T.platforms, p.platform)} ${pct(total ? p.requests / total : 0)}`} />
                  ))}
                </div>
              </Panel>
              <Panel title={T.us.calls}>
                {c.calls ? (
                  <>
                    <Lines
                      series={[
                        { name: T.lv.p50ttft, values: d.latency.map((l) => l.p50_ttft), color: "var(--c1)" },
                        { name: T.lv.p95ttft, values: d.latency.map((l) => l.p95_ttft), color: "var(--c5)" },
                        { name: T.lv.p95wait, values: d.latency.map((l) => l.p95_wait), color: "var(--warn)" },
                      ]}
                      labels={labels}
                      titles={d.latency.map((l) => `${labels[l.hour]}:00 · ${fmt(l.n)} ${T.us.calls}`)}
                      format={ms}
                      height={140}
                      fill={false}
                    />
                    <Legend className="mt-2" items={[{ name: T.lv.p50ttft, color: "var(--c1)" }, { name: T.lv.p95ttft, color: "var(--c5)" }, { name: T.lv.p95wait, color: "var(--warn)" }]} />
                    <div className="hint mt-4 mb-1">{T.us.statuses}</div>
                    <div className="scroll-x">
                      <table className="tbl">
                        <thead>
                          <tr>
                            <th>{T.g.model}</th>
                            {statuses.map((s) => (
                              <th key={s} className="num" style={{ color: statusColor(s) }}>
                                {nameOf(T.statuses, s)}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {Object.entries(d.by_model_status).map(([m, st]) => (
                            <tr key={m}>
                              <td>
                                <code>{m}</code>
                              </td>
                              {statuses.map((s) => (
                                <td key={s} className={cx("num", !st[s] && "text-ink-3")}>
                                  {st[s] ? fmt(st[s]) : "·"}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                ) : (
                  <Note>{T.us.callsNone}</Note>
                )}
              </Panel>
            </Grid>
            <Grid cols={2}>
              <Panel title={T.us.errors} sub={`${fmt(d.errors.reduce((a, e) => a + e.n, 0))}`}>
                <Ranks rows={d.errors.map((e) => ({ name: <span className="break-all whitespace-normal">{e.detail || T.g.unknown}</span>, value: e.n, color: "var(--bad)" }))} limit={12} />
              </Panel>
              <Panel title={T.us.rejected} sub={`${fmt(d.content_rejected.reduce((a, e) => a + e.n, 0))}`}>
                <Ranks rows={d.content_rejected.map((e) => ({ name: <span className="break-all whitespace-normal">{e.detail || T.g.unknown}</span>, value: e.n, color: "var(--c3)" }))} limit={12} />
              </Panel>
            </Grid>
            <Panel title={T.us.top} pad={false}>
              <DataTable rows={d.top_accounts} rowKey={(a) => a.account_id} defaultSort="cost_cny" columns={topCols} limit={25} />
            </Panel>
          </>
        );
      }}
    </Loaded>
  );
}
