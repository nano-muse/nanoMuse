/** The first page: the counts that matter today, the period's trend, where the money went,
 *  who spent it and what just happened. */

import type { PageProps } from "../App";
import { useData } from "../lib/hooks";
import { compact, fmt, money, when } from "../lib/format";
import { nameOf, useT } from "../lib/i18n";
import { useRoute } from "../lib/router";
import type { Overview as OverviewT, Series, Usage } from "../lib/types";
import { Bars, Lines, modelColor } from "../ui/charts";
import { Grid, Kpi, Kpis, Note, Panel, Pill } from "../ui/primitives";
import { IpChip, Who } from "../ui/who";
import { KindRanks, Loaded, ModelRanks, dayLabels, dayTitles } from "./common";

export function Overview({ days }: PageProps) {
  const T = useT();
  const route = useRoute();
  const ov = useData<OverviewT>(`/v1/admin/overview?days=${days}`, { poll: 60_000 });
  const se = useData<Series>(`/v1/admin/series?days=${days}`, { poll: 120_000 });
  const us = useData<Usage>(`/v1/admin/analytics/usage?days=${days}`, { poll: 120_000 });
  return (
    <Loaded q={ov}>
      {(d) => {
        const s = d.signals_today;
        const paused = d.settings.paused || [];
        return (
          <>
            {paused.length > 0 && <Note tone="warn">{T.ov.paused(paused.map((p) => nameOf(T.ct.names, p)).join(" · "))}</Note>}
            <Kpis>
              <Kpi label={T.ov.accounts} value={fmt(d.accounts.total)} sub={T.ov.accountsSub(d.accounts.disabled, d.accounts.unlimited)} />
              <Kpi label={T.ov.online} value={fmt(d.online_devices)} sub={T.ov.onlineSub(d.accounts.devices)} tone={d.online_devices > 0 ? "ok" : ""} />
              <Kpi label={T.ov.requestsToday} value={fmt(d.today.requests)} sub={T.ov.requestsSub(d.today.active_accounts, d.today.new_accounts)} />
              <Kpi label={T.ov.costToday} value={money(d.today.cost_cny)} sub={T.ov.costSub(d.week.cost_cny)} />
              <Kpi label={T.ov.liveKeys} value={fmt(d.accounts.live_keys)} sub={`${T.ov.withPassword} ${fmt(d.accounts.with_password)}`} />
              <Kpi label={T.ov.contrib} value={fmt(d.contributions.accounts)} sub={T.ov.contribSub(d.contributions.accounts, d.contributions.samples)} />
            </Kpis>
            <Panel title={T.ov.signals}>
              <div className="grid grid-cols-3 gap-2 md:grid-cols-6">
                <Kpi flat small label={T.ov.signIns} value={fmt(s.sign_ins)} />
                <Kpi flat small label={T.ov.signInFailures} value={fmt(s.sign_in_failures)} tone={s.sign_in_failures > 20 ? "warn" : ""} />
                <Kpi flat small label={T.ov.budgetRefusals} value={fmt(s.budget_refusals)} tone={s.budget_refusals > 0 ? "violet" : ""} />
                <Kpi flat small label={T.ov.upstreamErrors} value={fmt(s.upstream_errors)} tone={s.upstream_errors > 50 ? "bad" : s.upstream_errors > 0 ? "warn" : ""} />
                <Kpi flat small label={T.ov.contentRejected} value={fmt(s.content_rejected)} />
                <Kpi flat small label={T.ov.calls} value={fmt(s.calls)} />
              </div>
            </Panel>
            <Panel title={T.ov.trend(days)} sub={T.ov.moreUsage} right={<a href="#usage" className="btn sm">{T.nav.usage} →</a>}>
              {se.data ? (
                <div className="grid gap-4 lg:grid-cols-2">
                  <div>
                    {us.data ? (
                      <Bars
                        series={us.data.models.map((m) => ({ name: m.model, values: us.data!.rows.map((r) => Number(r.models[m.model]?.requests || 0)), color: modelColor(m.model) }))}
                        labels={dayLabels(us.data.rows.map((r) => r.day), Number(d.settings.day_offset_h || 0))}
                        titles={dayTitles(us.data.rows.map((r) => r.day), Number(d.settings.day_offset_h || 0))}
                        format={compact}
                        height={150}
                        onPick={(i) => route.go("usage", { day: us.data!.rows[i].day })}
                      />
                    ) : (
                      <div className="hint py-6 text-center">{T.g.loading}</div>
                    )}
                    <div className="hint mt-1">
                      {T.ov.trendCalls}
                      {us.data && us.data.models.length > 1 ? ` · ${us.data.models.map((m) => m.model).join(" · ")}` : ""}
                    </div>
                  </div>
                  <div>
                    <Lines
                      series={[
                        { name: T.ov.trendActive, values: se.data.days.map((x) => x.active_accounts), color: "var(--c2)" },
                        { name: T.ov.trendNew, values: se.data.days.map((x) => x.new_accounts), color: "var(--c4)" },
                      ]}
                      labels={dayLabels(se.data.days.map((x) => x.day), Number(d.settings.day_offset_h || 0))}
                      titles={dayTitles(se.data.days.map((x) => x.day), Number(d.settings.day_offset_h || 0))}
                      format={compact}
                      height={150}
                    />
                    <div className="hint mt-1">
                      {T.ov.trendActive} · {T.ov.trendNew}
                    </div>
                  </div>
                  <div className="lg:col-span-2">
                    <Lines
                      series={[
                        { name: T.ov.trendErrors, values: se.data.days.map((x) => x.upstream_errors), color: "var(--bad)" },
                        { name: T.ov.trendRefusals, values: se.data.days.map((x) => x.budget_refusals), color: "var(--violet)" },
                      ]}
                      labels={dayLabels(se.data.days.map((x) => x.day), Number(d.settings.day_offset_h || 0))}
                      titles={dayTitles(se.data.days.map((x) => x.day), Number(d.settings.day_offset_h || 0))}
                      format={compact}
                      height={110}
                      fill={false}
                    />
                    <div className="hint mt-1">
                      {T.ov.trendErrors} · {T.ov.trendRefusals}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="hint py-6 text-center">{T.g.loading}</div>
              )}
            </Panel>
            <Grid cols={3}>
              <Panel title={T.ov.byModel(days)} sub={`${fmt(d.period.requests)} ${T.g.requests} · ${money(d.period.cost_cny)}`}>
                <ModelRanks rows={d.period.by_model || []} limit={8} />
              </Panel>
              <Panel title={T.ov.byKind} sub={`${T.g.today} · ${money(d.today.cost_cny)}`}>
                <KindRanks rows={d.today.by_kind} />
                <div className="hint mt-3 mb-1">{T.ov.week}</div>
                <KindRanks rows={d.week.by_kind} />
              </Panel>
              <Panel title={T.ov.top}>
                <div className="flex flex-col gap-1.5">
                  {d.top_accounts.map((a) => (
                    <div key={a.account_id} className="flex items-center justify-between gap-2">
                      <Who id={a.account_id} hint={a.hint} identifier={a.identifier} />
                      <div className="text-right text-[12.5px]">
                        <div className="font-medium">{money(a.cost_cny)}</div>
                        <div className="hint">{fmt(a.requests)} {T.g.requests}</div>
                      </div>
                    </div>
                  ))}
                  {!d.top_accounts.length && <div className="hint py-4 text-center">{T.g.none}</div>}
                </div>
              </Panel>
            </Grid>
            <Panel title={T.ov.feed} right={<a href="#activity" className="btn sm">{T.nav.activity} →</a>}>
              <div className="flex flex-col divide-y divide-line">
                {d.events.map((e) => (
                  <div key={e.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5">
                    <span className="hint w-24 flex-none">{when(e.ts)}</span>
                    <Pill tone={e.kind.includes("failed") || e.kind.includes("error") ? "bad" : e.kind.includes("refused") || e.kind.includes("rejected") ? "warn" : e.kind.includes("created") ? "ok" : ""}>{nameOf(T.events, e.kind)}</Pill>
                    {e.account_id && <Who id={e.account_id} hint={e.hint} identifier={e.identifier} />}
                    <span className="sub min-w-0 flex-1 truncate" title={e.detail}>
                      {e.detail}
                    </span>
                    <IpChip ip={e.ip} className="hide-sm" />
                  </div>
                ))}
                {!d.events.length && <div className="hint py-4 text-center">{T.g.none}</div>}
              </div>
            </Panel>
          </>
        );
      }}
    </Loaded>
  );
}
