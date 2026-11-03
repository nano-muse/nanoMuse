/** The phone in the browser: who tried it, from where, and every demo started. */

import { useMemo, useState } from "react";
import type { PageProps } from "../App";
import { browserOf, clientLine, platformOf } from "../lib/client";
import { perDayVisits } from "../lib/demo";
import { dur, fmt, matches, nowS, siteDay, terms, when } from "../lib/format";
import { useData, useNow } from "../lib/hooks";
import { nameOf, useT, useZh } from "../lib/i18n";
import { useRoute } from "../lib/router";
import type { Demo as DemoT, DemoVisit, Overview, Places } from "../lib/types";
import { Bars, Ranks } from "../ui/charts";
import { Chips, DataTable, Grid, Kpi, Kpis, Note, Panel, Pill, Search } from "../ui/primitives";
import { Ago, IpChip, Who, identOf } from "../ui/who";
import { Loaded } from "./common";

export function Demo({ days }: PageProps) {
  const T = useT();
  const zh = useZh();
  const route = useRoute();
  const q = useData<DemoT>(`/v1/admin/demo?days=${days}`, { poll: 60_000 });
  const pv = useData<Places>(`/v1/admin/places?days=${days}`, { maxAge: 300_000 });
  const ov = useData<Overview>(`/v1/admin/overview?days=7`, { maxAge: 300_000 });
  const pick = route.params.get("s") || "";
  const [text, setText] = useState("");
  const offsetH = Number(ov.data?.settings.day_offset_h || 0);
  const perDay = useMemo(() => perDayVisits(q.data?.active, q.data?.visits, days, offsetH, nowS()), [q.data, days, offsetH]);
  return (
    <Loaded q={q}>
      {(d) => {
        if (!d.available) return <Note tone="warn">{T.de.off}</Note>;
        const visitors = d.visitors || [];
        const visits = d.visits || [];
        const active = d.active || [];
        const all = [...active, ...visits.filter((v) => !active.some((a) => a.id === v.id))];
        const sessions = all.filter((v) => !pick || (pick === "running" ? !v.ended : pick === "signed" ? !!v.visitor : pick === "anon" ? !v.visitor : pick === "byok" ? !!v.byok : true));
        const reasons = Object.entries(all.reduce((m, v) => { const k = v.ended ? nameOf(T.de.reason, v.reason || "?") : T.de.running; m[k] = (m[k] || 0) + 1; return m; }, {} as Record<string, number>)).sort((a, b) => b[1] - a[1]);
        const ts = terms(text);
        const shownVisitors = ts.length ? visitors.filter((v) => matches([identOf(v.id, v.hint), v.hint, v.id, v.last_ip, v.first_ip, v.last_ua, browserOf(v.last_ua)].filter(Boolean).join(" ").toLowerCase(), ts)) : visitors;
        return (
          <>
            <Kpis>
              <Kpi label={T.de.visitors} value={fmt(d.visitors_total || 0)} sub={d.signin_required === false ? T.de.noSignin : undefined} />
              <Kpi label={T.de.visits} value={fmt(visits.length)} sub={`/ ${fmt(d.visits_total || 0)}`} />
              <Kpi label={T.de.active} value={fmt(active.length)} tone={active.length ? "ok" : ""} />
              <Kpi label={T.de.byok} value={fmt(all.filter((v) => v.byok).length)} />
            </Kpis>
            <Grid cols={3}>
              <Panel title={T.de.perDay} sub={fmt(perDay.per.reduce((a, b) => a + b, 0))}>
                <Bars series={[{ name: T.de.visits, values: perDay.per, color: "var(--c5)" }]} labels={perDay.per.map((_, i) => siteDay(perDay.start + i * 86400, offsetH).slice(5))} height={130} />
              </Panel>
              <Panel title={T.de.reasons}>
                <Ranks rows={reasons.map(([name, value]) => ({ name, value, color: "var(--c4)" }))} showShare />
              </Panel>
              <Panel title={T.de.places}>
                {pv.data?.demo_visitors ? <Ranks rows={pv.data.demo_visitors.slice(0, 8).map((r) => ({ name: [r.country === "本地网络" ? T.g.local : r.country || T.plc.unknown, r.province].filter(Boolean).join(" · "), value: r.n, color: "var(--c5)" }))} showShare /> : <div className="hint py-4 text-center">{pv.data ? T.plc.noDemo : T.g.loading}</div>}
              </Panel>
            </Grid>
            <Grid cols={2}>
              <Panel title={T.de.visitors} right={<Search value={text} onChange={setText} placeholder={T.de.search} className="w-56" />} pad={false}>
                <DataTable
                  rows={shownVisitors}
                  rowKey={(v) => v.id}
                  defaultSort="last_seen"
                  limit={50}
                  maxHeight={560}
                  empty={T.de.none}
                  onRow={(v) => route.set({ acct: v.id })}
                  columns={[
                    { key: "hint", label: T.de.cols.hint, sortable: false, render: (v) => <Who id={v.id} hint={v.hint} channel={v.channel} tags={v.created ? <Pill tone="cyan">{T.de.created}</Pill> : null} stop /> },
                    { key: "signins", label: T.de.cols.signins, num: true, render: (v) => fmt(v.signins) },
                    { key: "sessions", label: T.de.cols.sessions, num: true, render: (v) => fmt(v.sessions) },
                    { key: "first_seen", label: T.de.cols.first, num: true, hideSm: true, render: (v) => when(v.first_seen) },
                    { key: "last_seen", label: T.de.cols.last, num: true, render: (v) => <Ago ts={v.last_seen} /> },
                    { key: "client", label: T.de.cols.client, sortable: false, hideSm: true, render: (v) => <span className="inline-flex flex-col"><span>{browserOf(v.last_ua)}</span><IpChip ip={v.last_ip} /></span> },
                  ]}
                />
              </Panel>
              <Panel title={T.de.visits} right={<Chips options={Object.entries(T.de.filters).map(([id, label]) => ({ id, label }))} value={pick} onChange={(v) => route.set({ s: v || null }, true)} />} pad={false}>
                <div className="flex flex-col divide-y divide-line px-4" style={{ maxHeight: 600, overflowY: "auto" }}>
                  {sessions.map((v) => (
                    <VisitRow key={v.id} v={v} zh={zh} />
                  ))}
                  {!sessions.length && <div className="hint py-8 text-center">{T.g.none}</div>}
                </div>
              </Panel>
            </Grid>
          </>
        );
      }}
    </Loaded>
  );
}

function VisitRow({ v, zh }: { v: DemoVisit; zh: boolean }) {
  const T = useT();
  const running = !v.ended;
  const now = useNow(10_000);
  const length = (v.ended || now) - v.started;
  return (
    <div className="flex items-start gap-3 py-2">
      <span className={`mt-1.5 inline-block h-2 w-2 flex-none rounded-full ${running ? "bg-ok pulse" : "bg-line-2"}`} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span>{when(v.started)}</span>
          {v.visitor ? <Who id={v.visitor} hint={v.hint} /> : <Pill>{T.de.anon}</Pill>}
          {running && <Pill tone="ok">{T.de.running}</Pill>}
          {v.byok && <Pill tone="violet">{T.de.byok}</Pill>}
        </div>
        <div className="sub flex flex-wrap gap-x-2">
          <span>{T.de.length} {dur(length, zh)}</span>
          {(v.requests || v.tokens) && <span>· {T.de.used(v.requests || 0, v.tokens || 0)}</span>}
          {v.model && <span>· <code>{v.model}</code></span>}
          {v.reason && !running && <span>· {T.de.why} {nameOf(T.de.reason, v.reason)}</span>}
          {v.ua && <span>· {platformOf(v.ua) === "browser" ? browserOf(v.ua) : clientLine(v.ua)}</span>}
          {v.ip && <span>· <IpChip ip={v.ip} /></span>}
        </div>
      </div>
      <code className="hint">{v.id.slice(0, 8)}</code>
    </div>
  );
}
