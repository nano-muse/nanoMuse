/** The kept turns' quality: how much is trivial or repeated, accounts by tier, the best
 *  and the worst, the prompts repeated most. Shapes only, never a text. */

import type { PageProps } from "../App";
import { bytes, compact, fmt, pct, siteDay } from "../lib/format";
import { useData } from "../lib/hooks";
import { nameOf, useT } from "../lib/i18n";
import type { Overview, Quality as QualityT, QualityAccount } from "../lib/types";
import { Bars, Donut, Legend, Ranks, platformColor } from "../ui/charts";
import { Bar, DataTable, Grid, Kpi, Kpis, Note, Panel, Pill, type Col } from "../ui/primitives";
import { Ago, PlatformPill, TierPill, Who } from "../ui/who";
import { Loaded, dayLabels } from "./common";

export function Quality({ days }: PageProps) {
  const T = useT();
  const q = useData<QualityT>(`/v1/admin/analytics/quality?days=${days}`, { poll: 300_000 });
  const ov = useData<Overview>("/v1/admin/overview?days=7", { maxAge: 300_000 });
  const offsetH = Number(ov.data?.settings.day_offset_h || 0);
  const accountCols: Col<QualityAccount>[] = [
    { key: "who", label: T.g.account, sortable: false, render: (a) => <Who id={a.account_id} hint={a.hint} identifier={a.identifier} disabled={a.disabled} tags={!a.contribute ? <Pill tone="warn">{T.qu.contributeOff}</Pill> : null} /> },
    { key: "score", label: T.qu.score, num: true, render: (a) => <span className="inline-flex items-center gap-2"><Bar value={a.score} max={100} tone={a.tier === "high" ? "ok" : a.tier === "low" ? "bad" : "warn"} className="w-14" />{a.score}</span> },
    { key: "tier", label: T.qu.tier, render: (a) => <TierPill tier={a.tier} /> },
    { key: "platform", label: T.g.platform, render: (a) => <PlatformPill platform={a.platform} /> },
    { key: "turns", label: T.g.turns, num: true, render: (a) => fmt(a.turns) },
    { key: "trivial", label: T.qu.trivial, num: true, render: (a) => fmt(a.trivial) },
    { key: "repeat_share", label: T.qu.repeat, num: true, render: (a) => pct(a.repeat_share) },
    { key: "hands", label: T.qu.hands, num: true, render: (a) => fmt(a.hands) },
    { key: "with_tools", label: T.qu.tools, num: true, hideSm: true, render: (a) => fmt(a.with_tools) },
    { key: "with_pictures", label: T.qu.pictures, num: true, hideSm: true, render: (a) => fmt(a.with_pictures) },
    { key: "avg_user_chars", label: T.qu.avgChars, num: true, hideSm: true, render: (a) => `${fmt(a.avg_user_chars)} / ${fmt(a.avg_reply_chars)}` },
    { key: "bytes", label: T.qu.bytes, num: true, hideSm: true, render: (a) => bytes(a.bytes) },
    { key: "last_ts", label: T.g.last, num: true, render: (a) => <Ago ts={a.last_ts} /> },
  ];
  return (
    <Loaded q={q}>
      {(d) => {
        const p = d.period;
        const useful = Math.max(0, p.turns - p.trivial - p.short_replies);
        const tierColor = (t: string) => (t === "high" ? "var(--ok)" : t === "low" ? "var(--bad)" : "var(--warn)");
        return (
          <>
            <Note>
              {T.qu.intro} {T.qu.coverage(d.coverage.described, d.coverage.samples)}
              {!d.coverage.backfill_done && <span className="ml-2 text-warn">{T.qu.backfilling}</span>}
            </Note>
            <Kpis>
              <Kpi label={T.qu.turns} value={fmt(p.turns)} sub={`${fmt(p.accounts)} ${T.qu.accounts} · ${bytes(p.bytes)}`} />
              <Kpi label={T.qu.trivial} value={pct(p.trivial_share, 1)} sub={`${fmt(p.trivial)} · ${T.qu.trivialSub(d.scoring.trivial_chars)}`} tone={p.trivial_share > 0.4 ? "bad" : p.trivial_share > 0.2 ? "warn" : ""} />
              <Kpi label={T.qu.repeated} value={pct(p.repeated_share, 1)} sub={`${fmt(p.repeated_turns)} · ${T.qu.repeatedSub(p.repeated_messages)}`} tone={p.repeated_share > 0.3 ? "bad" : p.repeated_share > 0.1 ? "warn" : ""} />
              <Kpi label={T.qu.hands} value={pct(p.turns ? p.hands / p.turns : 0, 1)} sub={`${fmt(p.hands)} · ${T.qu.tools} ${fmt(p.with_tools)} · ${T.qu.pictures} ${fmt(p.with_pictures)}`} />
              <Kpi label={T.qu.avgUser} value={fmt(p.avg_user_chars)} sub={`${T.qu.avgReply} ${fmt(p.avg_reply_chars)} · ${T.qu.avgMessages} ${p.avg_messages}`} />
              <Kpi label={T.g.distinct} value={pct(p.turns ? useful / p.turns : 0)} sub={`${fmt(useful)}`} tone="ok" />
            </Kpis>
            <Panel title={T.qu.series} sub={T.qu.allTime(d.all_time.turns, d.all_time.accounts, bytes(d.all_time.bytes))}>
              <Bars
                series={[
                  { name: T.qu.legendTrivial, values: d.series.map((r) => r.trivial), color: "var(--c3)" },
                  { name: T.qu.legendTurns, values: d.series.map((r) => Math.max(0, r.turns - r.trivial)), color: "var(--c1)" },
                ]}
                lines={[{ name: T.qu.accounts, values: d.series.map((r) => r.accounts), color: "var(--ink-3)" }]}
                labels={dayLabels(d.series.map((r) => r.day), offsetH)}
                titles={d.series.map((r) => `${siteDay(r.day, offsetH)} · ${fmt(r.turns)} ${T.g.turns} · ${compact(r.bytes)}B`)}
                format={fmt}
                height={150}
              />
              <Legend className="mt-2" items={[{ name: T.qu.legendTurns, color: "var(--c1)" }, { name: T.qu.legendTrivial, color: "var(--c3)" }, { name: T.qu.accounts, color: "var(--ink-3)" }]} />
            </Panel>
            <Grid cols={3}>
              <Panel title={T.qu.tiers} sub={T.qu.tiersSub}>
                <div className="flex items-center gap-4">
                  <Donut parts={d.tiers.map((t) => ({ name: nameOf(T.tiers, t.tier), value: t.accounts, color: tierColor(t.tier) }))} center={fmt(d.tiers.reduce((a, t) => a + t.accounts, 0))} />
                  <div className="min-w-0 flex-1">
                    <Ranks rows={d.tiers.map((t) => ({ name: nameOf(T.tiers, t.tier), value: t.accounts, sub: `${fmt(t.turns)} ${T.g.turns}`, color: tierColor(t.tier) }))} showShare />
                  </div>
                </div>
                <div className="hint mt-3">{T.qu.scoringText(d.scoring.full_depth_turns)}</div>
              </Panel>
              <Panel title={T.qu.byPlatform} pad={false}>
                <DataTable
                  rows={d.by_platform}
                  rowKey={(r) => r.platform}
                  defaultSort="turns"
                  columns={[
                    { key: "platform", label: T.g.platform, render: (r) => <PlatformPill platform={r.platform} /> },
                    { key: "turns", label: T.g.turns, num: true, render: (r) => fmt(r.turns) },
                    { key: "accounts", label: T.g.accounts, num: true, render: (r) => fmt(r.accounts) },
                    { key: "trivial", label: T.qu.trivial, num: true, value: (r) => (r.turns ? r.trivial / r.turns : 0), render: (r) => pct(r.turns ? r.trivial / r.turns : 0) },
                    { key: "hands", label: T.qu.hands, num: true, value: (r) => (r.turns ? r.hands / r.turns : 0), render: (r) => pct(r.turns ? r.hands / r.turns : 0) },
                    { key: "with_pictures", label: T.qu.pictures, num: true, value: (r) => (r.turns ? r.with_pictures / r.turns : 0), render: (r) => pct(r.turns ? r.with_pictures / r.turns : 0) },
                    { key: "avg_user_chars", label: T.qu.avgChars, num: true, render: (r) => fmt(r.avg_user_chars) },
                  ]}
                />
                <div className="px-4 pb-3">
                  <div className="mt-2 flex h-2 w-full overflow-hidden rounded-full bg-fill">
                    {d.by_platform.map((r) => (
                      <span key={r.platform} style={{ width: `${p.turns ? (100 * r.turns) / p.turns : 0}%`, background: platformColor(r.platform) }} />
                    ))}
                  </div>
                </div>
              </Panel>
              <Panel title={T.qu.repeats} pad={false}>
                <DataTable
                  rows={d.top_repeats}
                  rowKey={(r) => r.hash}
                  defaultSort="turns"
                  limit={12}
                  columns={[
                    { key: "hash", label: T.qu.hash, render: (r) => <code className="text-ink-3">{r.hash.slice(0, 10)}</code> },
                    { key: "chars", label: T.qu.avgChars, num: true, render: (r) => fmt(r.chars) },
                    { key: "turns", label: T.g.turns, num: true, render: (r) => fmt(r.turns) },
                    { key: "accounts", label: T.g.accounts, num: true, render: (r) => fmt(r.accounts) },
                  ]}
                />
              </Panel>
            </Grid>
            <Panel title={T.qu.top} pad={false}>
              <DataTable rows={d.top_accounts} rowKey={(a) => a.account_id} defaultSort="score" columns={accountCols} limit={20} />
            </Panel>
            <Grid cols={2}>
              <Panel title={T.qu.low} pad={false}>
                <DataTable rows={d.low_accounts} rowKey={(a) => a.account_id} defaultSort="turns" columns={accountCols.filter((c) => !["with_tools", "with_pictures", "avg_user_chars", "bytes"].includes(c.key))} limit={15} />
              </Panel>
              <Panel title={T.qu.scripted} pad={false}>
                <DataTable rows={d.scripted_accounts} rowKey={(a) => a.account_id} defaultSort="turns" columns={accountCols.filter((c) => !["with_tools", "with_pictures", "avg_user_chars", "bytes", "hands"].includes(c.key))} limit={15} />
              </Panel>
            </Grid>
          </>
        );
      }}
    </Loaded>
  );
}
