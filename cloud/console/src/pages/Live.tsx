/** The model endpoint right now: the gate, the requests under way, the last hour minute by
 *  minute, latency percentiles, and the calls that just ended. Polls every 3 seconds. */

import { useMemo } from "react";
import { clock, compact, fmt, ms, pct } from "../lib/format";
import { useData, useNow } from "../lib/hooks";
import { nameOf, useT } from "../lib/i18n";
import type { Live, LiveSummary, UpstreamGate } from "../lib/types";
import { Bars, Legend, Lines, statusColor } from "../ui/charts";
import { Grid, Kpi, Note, Panel, Pill, cx } from "../ui/primitives";
import { Flags, PlatformPill, StatusPill } from "../ui/who";
import { GatePanel } from "./GatePanel";
import { Loaded, Updated } from "./common";

type Verdict = "smooth" | "busy" | "saturated";
const verdictOf = (s: LiveSummary, gates: UpstreamGate[]): Verdict => {
  if (gates.some((gate) => gate.waiting > 0 && gate.active >= gate.limit)) return "saturated";
  if (s.waited_share > 0.25 || s.p95_wait_ms > 2000) return "saturated";
  if (s.waited_share > 0.05 || s.p95_wait_ms > 500 || gates.some((gate) => gate.active >= gate.limit * 0.75)) return "busy";
  return "smooth";
};

function Summary({ s, title }: { s: LiveSummary; title: string }) {
  const T = useT();
  const errRate = s.requests ? s.errors / s.requests : 0;
  return (
    <Panel title={title} sub={`${fmt(s.requests)} ${T.g.requests} · ${fmt(s.accounts)} ${T.g.accounts}`}>
      <div className="grid grid-cols-2 gap-x-3 gap-y-2 md:grid-cols-4">
        <Kpi flat small label={T.lv.p50ttft} value={ms(s.p50_ttft_ms)} tone={s.p50_ttft_ms > 3000 ? "warn" : ""} />
        <Kpi flat small label={T.lv.p95ttft} value={ms(s.p95_ttft_ms)} tone={s.p95_ttft_ms > 8000 ? "bad" : s.p95_ttft_ms > 4000 ? "warn" : ""} />
        <Kpi flat small label={T.lv.p50total} value={ms(s.p50_total_ms)} />
        <Kpi flat small label={T.lv.p95total} value={ms(s.p95_total_ms)} />
        <Kpi flat small label={T.lv.waitedShare} value={pct(s.waited_share, 1)} tone={s.waited_share > 0.25 ? "bad" : s.waited_share > 0.05 ? "warn" : "ok"} />
        <Kpi flat small label={T.lv.p95wait} value={ms(s.p95_wait_ms)} tone={s.p95_wait_ms > 2000 ? "bad" : s.p95_wait_ms > 500 ? "warn" : ""} />
        <Kpi flat small label={T.lv.errRate} value={pct(errRate, 1)} sub={`${fmt(s.errors)} ${T.g.errors} · ${fmt(s.refused)} ${T.g.refused}`} tone={errRate > 0.1 ? "bad" : errRate > 0.03 ? "warn" : ""} />
        <Kpi flat small label={T.lv.tokensPerS} value={fmt(s.tokens_out_per_s)} sub={`${compact(s.tokens_out)} ${T.g.tokensOut}`} />
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {Object.entries(s.by_status)
          .sort((a, b) => b[1] - a[1])
          .map(([k, v]) => (
            <span key={k} className="pill" style={{ color: statusColor(k) }}>
              {nameOf(T.statuses, k)} {fmt(v)}
            </span>
          ))}
        <Pill>{T.g.hands} {fmt(s.hands)}</Pill>
        <Pill>{T.g.images} {fmt(s.with_images)}</Pill>
        <Pill>{T.lv.streamShare} {pct(s.stream_share)}</Pill>
      </div>
    </Panel>
  );
}

export function LivePage() {
  const T = useT();
  const q = useData<Live>("/v1/admin/live", { poll: 3000, maxAge: 1000 });
  const nowS = useNow(1000);
  const view = useMemo(() => q.data, [q.data]);
  return (
    <Loaded q={q}>
      {() => {
        const d = view!;
        const modelGates = Object.entries(d.model_gates ?? {});
        const verdict = verdictOf(d.last_10m, modelGates.length ? modelGates.map(([, gate]) => gate) : [d.gate]);
        const labels = d.minutes.map((m) => clock(m.t));
        const now = nowS * 1000;
        const drift = Math.max(0, Math.round((now - q.at) / 1000));
        return (
          <>
            <Note tone={verdict === "smooth" ? "ok" : verdict === "busy" ? "warn" : "bad"}>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="font-medium">{verdict === "smooth" ? T.lv.verdictSmooth : verdict === "busy" ? T.lv.verdictBusy : T.lv.verdictSaturated}</span>
                <span className="ml-auto opacity-70">
                  <Updated at={q.at} />
                  {drift > 6 && <span className="ml-2">({drift} s)</span>}
                </span>
              </div>
              <div className="mt-1 text-[12px] opacity-80">{T.lv.verdictHow}</div>
            </Note>
            <Grid cols={3}>
              <GatePanel gate={d.gate} models={modelGates} />
              <Panel title={T.lv.inFlight} sub={T.lv.inFlightSub(d.in_flight.accounts, d.in_flight.limit)}>
                <div className="kpi">
                  <div className="v">{d.in_flight.requests}</div>
                  <div className="sub">{T.lv.running(d.running.length)}</div>
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {(["waiting", "upstream", "streaming"] as const).map((ph) => {
                    const n = d.running.filter((r) => r.phase === ph).length;
                    return (
                      <Pill key={ph} tone={ph === "waiting" ? (n ? "bad" : "") : ph === "streaming" ? "ok" : "accent"}>
                        {T.phases[ph]} {n}
                      </Pill>
                    );
                  })}
                </div>
              </Panel>
              <Panel title={T.lv.hub} sub={d.hub ? T.lv.hubSub(d.hub.accounts_online, d.hub.pending_calls) : T.lv.noHub}>
                <div className="kpi">
                  <div className="v">{d.hub ? fmt(d.hub.online) : "·"}</div>
                  <div className="sub">{T.g.devices} · {T.g.online}</div>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-[12px] text-ink-2">
                  {!modelGates.length && <>
                    <span>{T.lv.concurrency}</span>
                    <span className="text-right">{d.settings.chat_concurrency}</span>
                  </>}
                  <span>{T.lv.maxInFlight}</span>
                  <span className="text-right">{d.settings.max_in_flight}</span>
                  <span>{T.lv.timeout}</span>
                  <span className="text-right">{d.settings.upstream_timeout_s} s</span>
                  <span>{T.lv.retries}</span>
                  <span className="text-right">{d.settings.chat_retries}</span>
                </div>
              </Panel>
            </Grid>
            <Grid cols={2}>
              <Summary s={d.last_10m} title={T.lv.last10} />
              <Summary s={d.last_hour} title={T.lv.lastHour} />
            </Grid>
            <Panel title={T.lv.perMinute} sub={T.lv.pollNote}>
              <Bars
                series={[
                  { name: T.lv.legendOk, values: d.minutes.map((m) => m.ok), color: "var(--ok)" },
                  { name: T.lv.legendErr, values: d.minutes.map((m) => m.errors), color: "var(--bad)" },
                  { name: T.lv.legendRefused, values: d.minutes.map((m) => m.refused), color: "var(--violet)" },
                  { name: T.g.other, values: d.minutes.map((m) => Math.max(0, m.n - m.ok - m.errors - m.refused)), color: "var(--ink-3)" },
                ]}
                lines={[{ name: T.lv.legendWaited, values: d.minutes.map((m) => m.waited), color: "var(--warn)" }]}
                labels={labels}
                height={150}
              />
              <Legend
                className="mt-2"
                items={[
                  { name: T.lv.legendOk, color: "var(--ok)" },
                  { name: T.lv.legendErr, color: "var(--bad)" },
                  { name: T.lv.legendRefused, color: "var(--violet)" },
                  { name: T.lv.legendWaited, color: "var(--warn)" },
                ]}
              />
            </Panel>
            <Grid cols={2}>
              <Panel title={T.lv.latencyMinute}>
                <Lines
                  series={[
                    { name: T.lv.p50ttft, values: d.minutes.map((m) => m.p50_ttft), color: "var(--c1)" },
                    { name: T.lv.p95total, values: d.minutes.map((m) => m.p95_total), color: "var(--c4)" },
                    { name: T.lv.p95wait, values: d.minutes.map((m) => m.p95_wait), color: "var(--warn)" },
                  ]}
                  labels={labels}
                  format={ms}
                  height={150}
                  fill={false}
                />
                <Legend
                  className="mt-2"
                  items={[
                    { name: T.lv.p50ttft, color: "var(--c1)" },
                    { name: T.lv.p95total, color: "var(--c4)" },
                    { name: T.lv.p95wait, color: "var(--warn)" },
                  ]}
                />
              </Panel>
              <Panel title={T.lv.tokensMinute}>
                <Bars series={[{ name: T.g.tokensOut, values: d.minutes.map((m) => m.tokens_out), color: "var(--c5)" }]} labels={labels} format={compact} height={150} />
              </Panel>
            </Grid>
            <Panel title={T.lv.running(d.running.length)} pad={false}>
              {d.running.length ? (
                <div className="scroll-x">
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>{T.g.time}</th>
                        <th>{T.lv.account}</th>
                        <th>{T.g.platform}</th>
                        <th>{T.g.model}</th>
                        <th>{T.g.phase}</th>
                        <th className="num">{T.g.age}</th>
                        <th className="num">{T.g.wait}</th>
                        <th className="num">{T.g.ttft}</th>
                        <th className="num">{T.lv.tokens}</th>
                        <th>{T.lv.flags}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.running.map((r) => (
                        <tr key={r.id}>
                          <td>{clock(r.ts, true)}</td>
                          <td>
                            <code>{r.account}</code>
                          </td>
                          <td>
                            <PlatformPill platform={r.platform} />
                          </td>
                          <td>
                            <code>{r.model}</code>
                          </td>
                          <td>
                            <Pill tone={r.phase === "waiting" ? "bad" : r.phase === "streaming" ? "ok" : "accent"} className={r.phase === "waiting" ? "pulse" : ""}>
                              {T.phases[r.phase]}
                            </Pill>
                          </td>
                          <td className="num">{ms(r.age_ms)}</td>
                          <td className={cx("num", r.wait_ms > 500 && "text-warn")}>{ms(r.wait_ms)}</td>
                          <td className="num">{r.ttft_ms === null ? "·" : ms(r.ttft_ms)}</td>
                          <td className="num">{fmt(r.tokens_out)}</td>
                          <td>
                            <Flags hands={r.hands} images={r.images} stream={r.stream} retries={r.retries} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="hint px-4 py-6 text-center">{T.lv.noneRunning}</div>
              )}
            </Panel>
            <Panel title={T.lv.recent} sub={T.lv.sinceStart(clock(d.since_start.started_at)) + " · " + Object.entries(d.since_start.counts).filter(([, v]) => v).map(([k, v]) => `${nameOf(T.statuses, k)} ${fmt(v)}`).join(" · ")} pad={false}>
              <div className="scroll-x" style={{ maxHeight: 520, overflowY: "auto" }}>
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>{T.g.time}</th>
                      <th>{T.lv.account}</th>
                      <th>{T.g.platform}</th>
                      <th className="hide-sm">{T.g.model}</th>
                      <th>{T.g.status}</th>
                      <th className="num">{T.g.wait}</th>
                      <th className="num">{T.g.ttft}</th>
                      <th className="num">{T.g.totalTime}</th>
                      <th className="num">{T.lv.tokens}</th>
                      <th>{T.lv.flags}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.recent.map((r, i) => (
                      <tr key={`${r.ts}-${i}`}>
                        <td>{clock(r.ts, true)}</td>
                        <td>
                          <code>{r.account}</code>
                        </td>
                        <td>
                          <PlatformPill platform={r.platform} />
                        </td>
                        <td className="hide-sm">
                          <code>{r.model}</code>
                        </td>
                        <td>
                          <StatusPill status={r.status} detail={r.detail} />
                          {r.detail && r.status !== "ok" && <span className="hint ml-1.5 inline-block max-w-[220px] truncate align-middle">{r.detail}</span>}
                        </td>
                        <td className={cx("num", r.wait_ms > 500 && "text-warn")}>{ms(r.wait_ms)}</td>
                        <td className="num">{r.status === "ok" ? ms(r.ttft_ms) : "·"}</td>
                        <td className="num">{ms(r.total_ms)}</td>
                        <td className="num" title={`${fmt(r.prompt_tokens)} in`}>
                          {fmt(r.completion_tokens)}
                        </td>
                        <td>
                          <Flags hands={r.hands} images={r.images} tools={r.tools} stream={r.stream} retries={r.retries} />
                        </td>
                      </tr>
                    ))}
                    {!d.recent.length && (
                      <tr>
                        <td colSpan={10} className="hint py-6 text-center">
                          {T.g.none}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </Panel>
          </>
        );
      }}
    </Loaded>
  );
}
