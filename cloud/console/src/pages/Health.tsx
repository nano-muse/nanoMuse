/** What the self-check reads, for a person: problems first, then the counters. */

import { bytes, fmt, when } from "../lib/format";
import { useData } from "../lib/hooks";
import { useT } from "../lib/i18n";
import type { Health } from "../lib/types";
import { Grid, Kpi, Note, Panel } from "../ui/primitives";
import { Who } from "../ui/who";
import { GatePanel } from "./GatePanel";
import { Loaded, Updated } from "./common";

export function HealthPage() {
  const T = useT();
  const q = useData<Health>("/v1/admin/health", { poll: 30_000, maxAge: 5000 });
  return (
    <Loaded q={q}>
      {(h) => (
        <>
          <Note tone={h.ok ? "ok" : "bad"}>
            <div className="flex flex-wrap items-center gap-3">
              <span className="font-medium">{h.ok ? T.he.ok : T.he.problems}</span>
              <span className="ml-auto opacity-70">
                {T.he.version} {h.version} · {when(h.time)} · <Updated at={q.at} /> · {T.he.refresh}
              </span>
            </div>
            {h.problems.length > 0 && (
              <ul className="mt-2 mb-0 list-disc pl-5">
                {h.problems.map((p, i) => (
                  <li key={i}>{p}</li>
                ))}
              </ul>
            )}
          </Note>
          <Grid cols={3}>
            <GatePanel gate={h.chat_upstream} models={Object.entries(h.model_gates ?? {})} retries={h.chat_upstream.retries} />
            <Panel title={T.he.inFlight} sub={T.lv.inFlightSub(h.in_flight.accounts, h.in_flight.limit)}>
              <div className="kpi">
                <div className="v">{h.in_flight.requests}</div>
                <div className="sub">{fmt(h.in_flight.accounts)} {T.g.accounts}</div>
              </div>
            </Panel>
            <Panel title={T.he.hub} sub={h.hub ? T.he.hubDrops(h.hub.dropped_frames, h.hub.flood_closes, h.hub.slow_closes, h.hub.refused_connections ?? 0) : T.lv.noHub}>
              <div className="kpi">
                <div className="v">{h.hub ? fmt(h.hub.online) : "·"}</div>
                <div className="sub">{h.hub ? `${T.he.hubOnline(h.hub.online, h.hub.accounts_online)} · ${T.he.pending} ${h.hub.pending_calls}` : ""}</div>
              </div>
            </Panel>
          </Grid>
          <Panel title={T.he.lastHour}>
            <div className="grid grid-cols-3 gap-2 md:grid-cols-6">
              <Kpi flat small label={T.g.requests} value={fmt(h.last_hour.requests)} />
              <Kpi flat small label={T.ov.upstreamErrors} value={fmt(h.last_hour.upstream_errors)} tone={h.last_hour.upstream_errors >= 20 ? "bad" : h.last_hour.upstream_errors > 0 ? "warn" : ""} />
              <Kpi flat small label={T.ov.contentRejected} value={fmt(h.last_hour.content_rejected)} />
              <Kpi flat small label={T.ov.budgetRefusals} value={fmt(h.last_hour.budget_refused)} />
              <Kpi flat small label={T.ov.signIns} value={fmt(h.last_hour.sign_ins)} />
              <Kpi flat small label={T.ov.signInFailures} value={fmt(h.last_hour.sign_in_failures)} tone={h.last_hour.sign_in_failures > 20 ? "warn" : ""} />
            </div>
          </Panel>
          <Grid cols={2}>
            <Panel title={T.he.db}>
              <div className="kpi">
                <div className={`v sm ${h.db.writable ? "" : "text-bad"}`}>{bytes(h.db.size_bytes)}</div>
                <div className="sub">{h.db.writable ? T.he.writable : T.he.notWritable}</div>
              </div>
            </Panel>
            <Panel title={T.he.key}>
              <div className="kpi">
                <div className={`v sm ${h.upstream_key ? "text-ok" : "text-bad"}`}>{h.upstream_key ? T.he.keySet : T.he.keyMissing}</div>
              </div>
            </Panel>
          </Grid>
          {h.alerts.length > 0 && (
            <Panel title={T.he.alerts}>
              <div className="flex flex-col gap-2">
                {h.alerts.map((a, i) => (
                  <div key={i} className="rounded-lg bg-warn-soft px-3 py-2 text-[12.5px] text-warn">
                    <div className="flex flex-wrap items-center gap-2">
                      <span>{a.message}</span>
                      {a.account_id && <Who id={a.account_id} />}
                    </div>
                    <div className="opacity-80">{a.hint}</div>
                  </div>
                ))}
              </div>
            </Panel>
          )}
        </>
      )}
    </Loaded>
  );
}
