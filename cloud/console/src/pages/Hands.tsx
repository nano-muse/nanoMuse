/** Screen operation: how many cloud turns carried operator tools, by day, platform and
 *  tool; the accounts that used it; the devices that can be operated. */

import type { PageProps } from "../App";
import { fmt, pct, siteDay } from "../lib/format";
import { useData } from "../lib/hooks";
import { nameOf, useT } from "../lib/i18n";
import type { Hands as HandsT, Overview } from "../lib/types";
import { Bars, Legend, Ranks, platformColor } from "../ui/charts";
import { DataTable, Grid, Kpi, Kpis, Note, Panel, Pill } from "../ui/primitives";
import { Ago, PlatformPill, Who } from "../ui/who";
import { Loaded, dayLabels } from "./common";

export function Hands({ days }: PageProps) {
  const T = useT();
  const q = useData<HandsT>(`/v1/admin/analytics/hands?days=${days}`, { poll: 300_000 });
  const ov = useData<Overview>("/v1/admin/overview?days=7", { maxAge: 300_000 });
  const offsetH = Number(ov.data?.settings.day_offset_h || 0);
  return (
    <Loaded q={q}>
      {(d) => {
        const s = d.summary;
        const platforms = Object.keys(d.days_series.reduce((m, r) => Object.assign(m, r.platforms), {} as Record<string, number>));
        return (
          <>
            <Note>{T.ha.intro}</Note>
            <Kpis>
              <Kpi label={T.ha.hands} value={fmt(s.hands)} sub={`/ ${fmt(s.calls)} ${T.ha.calls}`} tone="violet" />
              <Kpi label={T.ha.share} value={pct(s.hands_share, 1)} />
              <Kpi label={T.ha.accounts} value={fmt(s.hands_accounts)} />
              <Kpi label={T.ha.operable} value={fmt(s.accounts_with_operable_device)} />
              <Kpi label={T.ha.samples} value={fmt(d.samples.hands)} sub={T.ha.samplesSub(d.samples.hands, d.samples.turns)} />
              <Kpi label={T.ha.tools} value={d.tools.filter((t) => t.hands).length} sub={d.tools.filter((t) => t.hands).slice(0, 3).map((t) => t.tool).join(", ")} small />
            </Kpis>
            <Panel title={T.ha.series}>
              <Bars
                series={platforms.map((p) => ({ name: nameOf(T.platforms, p), values: d.days_series.map((r) => r.platforms[p] || 0), color: platformColor(p) }))}
                lines={[{ name: T.ha.accounts, values: d.days_series.map((r) => r.hands_accounts), color: "var(--ink-3)" }]}
                labels={dayLabels(d.days_series.map((r) => r.day), offsetH)}
                titles={d.days_series.map((r) => `${siteDay(r.day, offsetH)} · ${fmt(r.hands)} / ${fmt(r.calls)}`)}
                height={160}
              />
              <Legend className="mt-2" items={[...platforms.map((p) => ({ name: nameOf(T.platforms, p), color: platformColor(p) })), { name: T.ha.accounts, color: "var(--ink-3)" }]} />
            </Panel>
            <Grid cols={2}>
              <Panel title={T.ha.byPlatform} pad={false}>
                <DataTable
                  rows={d.platforms}
                  rowKey={(p) => p.platform}
                  defaultSort="hands"
                  columns={[
                    { key: "platform", label: T.g.platform, render: (p) => <PlatformPill platform={p.platform} /> },
                    { key: "calls", label: T.ha.calls, num: true, render: (p) => fmt(p.calls) },
                    { key: "hands", label: T.ha.hands, num: true, render: (p) => fmt(p.hands) },
                    { key: "share", label: T.ha.share, num: true, value: (p) => (p.calls ? p.hands / p.calls : 0), render: (p) => pct(p.calls ? p.hands / p.calls : 0, 1) },
                    { key: "ok", label: T.g.ok, num: true, render: (p) => fmt(p.ok) },
                    { key: "errors", label: T.g.errors, num: true, render: (p) => fmt(p.errors) },
                    { key: "with_images", label: T.g.images, num: true, render: (p) => fmt(p.with_images) },
                  ]}
                />
              </Panel>
              <Panel title={T.ha.devices} sub={`${T.ha.screen} · ${T.ha.screen30}`} pad={false}>
                <DataTable
                  rows={d.devices}
                  rowKey={(g) => g.kind}
                  defaultSort="devices"
                  columns={[
                    { key: "kind", label: T.pl.deviceKind },
                    { key: "devices", label: T.g.devices, num: true, render: (g) => fmt(g.devices) },
                    { key: "screen", label: T.ha.screen, num: true, render: (g) => fmt(g.screen) },
                    { key: "screen_seen_30d", label: T.ha.screen30, num: true, render: (g) => fmt(g.screen_seen_30d) },
                  ]}
                />
                <div className="px-4 py-3">
                  <div className="hint mb-1">{T.ha.samples}</div>
                  <Ranks rows={d.samples.by_platform.map((p) => ({ name: nameOf(T.platforms, p.platform), value: p.hands, sub: `${fmt(p.turns)} ${T.g.turns} · ${fmt(p.accounts)} ${T.g.accounts}`, color: platformColor(p.platform) }))} />
                </div>
              </Panel>
            </Grid>
            <Grid cols={2}>
              <Panel title={T.ha.tools} sub={`${T.ha.which}: ${d.hands_tools.join(", ")} · ${T.ha.prefixes}: ${d.hands_prefixes.join(", ")}`} pad={false}>
                <DataTable
                  rows={d.tools}
                  rowKey={(t) => t.tool}
                  defaultSort="calls"
                  limit={20}
                  columns={[
                    { key: "tool", label: T.ha.tool, render: (t) => <code>{t.tool}</code> },
                    { key: "hands", label: T.ha.isHands, render: (t) => (t.hands ? <Pill tone="violet">{T.ha.legendHands}</Pill> : <Pill>{T.ha.legendOther}</Pill>) },
                    { key: "calls", label: T.ha.calls, num: true, render: (t) => fmt(t.calls) },
                    { key: "platforms", label: T.g.platform, sortable: false, render: (t) => <span className="hint">{Object.entries(t.platforms).sort((a, b) => b[1] - a[1]).map(([p, n]) => `${nameOf(T.platforms, p)} ${fmt(n)}`).join(" · ")}</span> },
                  ]}
                />
              </Panel>
              <Panel title={T.ha.list} pad={false}>
                <DataTable
                  rows={d.accounts}
                  rowKey={(a) => a.account_id}
                  defaultSort="turns"
                  limit={20}
                  columns={[
                    { key: "who", label: T.g.account, sortable: false, render: (a) => <Who id={a.account_id} hint={a.hint} identifier={a.identifier} /> },
                    { key: "turns", label: T.ha.turns, num: true, render: (a) => fmt(a.turns) },
                    { key: "ok", label: T.g.ok, num: true, render: (a) => fmt(a.ok) },
                    { key: "platforms", label: T.g.platform, render: (a) => <span className="hint">{a.platforms.split(",").filter(Boolean).map((p) => nameOf(T.platforms, p)).join(" · ")}</span> },
                    { key: "last_ts", label: T.g.last, num: true, render: (a) => <Ago ts={a.last_ts} /> },
                  ]}
                />
              </Panel>
            </Grid>
          </>
        );
      }}
    </Loaded>
  );
}
