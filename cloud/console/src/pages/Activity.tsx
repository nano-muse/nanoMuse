/** What happens day by day, and the feed of everyone's events, filtered by kind and paged. */

import { useCallback, useEffect, useRef, useState } from "react";
import type { PageProps } from "../App";
import { get, qs } from "../lib/api";
import { compact, dateOf, fmt, when } from "../lib/format";
import { useData } from "../lib/hooks";
import { nameOf, useT } from "../lib/i18n";
import { useRoute } from "../lib/router";
import { LatestRequest } from "../lib/latest-request";
import type { EventRow, Series } from "../lib/types";
import { Legend, Lines } from "../ui/charts";
import { Btn, Chips, Grid, Note, Panel, Pill } from "../ui/primitives";
import { IpChip, PlatformPill, Who } from "../ui/who";
import { Loaded, dayLabels, dayTitles } from "./common";

const FILTERS: [string, string][] = [
  ["", ""],
  ["sign_in.code,sign_in.password,sign_in.session,sign_in.failed,account.created", "signIns"],
  ["budget.refused", "refusals"],
  ["upstream.error", "errors"],
  ["content.rejected", "contentChecks"],
  ["call.ended", "calls"],
  ["password.set,password.changed,password.cleared", "passwords"],
];

export function Activity({ days }: PageProps) {
  const T = useT();
  const route = useRoute();
  const kind = route.params.get("k") || "";
  const se = useData<Series>(`/v1/admin/series?days=${days}`, { poll: 120_000 });
  const [events, setEvents] = useState<EventRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  // a page asked for under an older filter (or the poll racing a "More") must not
  // land under the newer list, nor clear its loading flag
  const requests = useRef(new LatestRequest());
  const load = useCallback(
    (before: number) => requests.current.run(
      () => get<{ events: EventRow[] }>(`/v1/admin/events${qs({ limit: 200, kind, before })}`),
      {
        start: () => { setLoading(true); setError(""); },
        success: (r) => {
          setEvents((xs) => (before ? [...xs, ...r.events] : r.events));
          setDone(r.events.length < 200);
        },
        error: (e) => setError(e instanceof Error ? e.message : String(e)),
        finish: () => setLoading(false),
      },
    ),
    [kind],
  );
  useEffect(() => {
    const pending = requests.current;
    setEvents([]);
    setDone(false);
    void load(0);
    const id = setInterval(() => {
      if (document.visibilityState === "visible") void load(0);
    }, 30_000);
    return () => {
      clearInterval(id);
      pending.invalidate();
    };
  }, [load]);
  return (
    <>
      <Loaded q={se}>
        {(d) => {
          const labels = dayLabels(d.days.map((x) => x.day));
          const titles = dayTitles(d.days.map((x) => x.day));
          const L = (k: keyof typeof T.at.series, key: keyof Series["days"][number], color: string) => ({ name: T.at.series[k], values: d.days.map((x) => Number(x[key] || 0)), color });
          const blocks: { series: ReturnType<typeof L>[]; title: string }[] = [
            { title: T.at.series.calls, series: [L("calls", "calls", "var(--c1)")] },
            { title: `${T.at.series.active} · ${T.at.series.new}`, series: [L("active", "active_accounts", "var(--c2)"), L("new", "new_accounts", "var(--c4)")] },
            { title: `${T.at.series.signIns} · ${T.at.series.failures}`, series: [L("signIns", "sign_ins", "var(--c5)"), L("failures", "sign_in_failures", "var(--bad)")] },
            { title: `${T.at.series.refusals} · ${T.at.series.errors} · ${T.at.series.rejected}`, series: [L("refusals", "budget_refusals", "var(--violet)"), L("errors", "upstream_errors", "var(--bad)"), L("rejected", "content_rejected", "var(--c3)")] },
            { title: `${T.at.series.invites} · ${T.at.series.contribute}`, series: [L("invites", "invites_used", "var(--c6)"), L("contribute", "contribute_on", "var(--c7)")] },
          ];
          return (
            <Panel title={T.at.title(days)} sub={`${T.g.online} ${fmt(d.online_devices)} · ${T.ov.contrib} ${fmt(d.contributors)}`}>
              <Grid cols={2}>
                {blocks.map((b, i) => (
                  <div key={i}>
                    <Lines series={b.series} labels={labels} titles={titles} format={compact} height={130} fill={b.series.length === 1} />
                    <Legend className="mt-1" items={b.series.map((s) => ({ name: s.name, color: s.color }))} />
                  </div>
                ))}
                {d.web && (
                  <div>
                    <div className="hint mb-1">{T.at.web}</div>
                    <pre className="m-0 overflow-auto rounded-lg bg-panel-2 p-3 text-[12px]">{JSON.stringify(d.web, null, 1)}</pre>
                  </div>
                )}
              </Grid>
            </Panel>
          );
        }}
      </Loaded>
      <Panel title={T.at.feed} right={<Chips options={FILTERS.map(([v, k]) => ({ id: v, label: T.evFilters[k] }))} value={kind} onChange={(v) => route.set({ k: v || null }, true)} />} pad={false}>
        {error && <Note tone="bad" className="m-3">{error}</Note>}
        <div className="flex flex-col divide-y divide-line px-4">
          {events.map((e) => (
            <div key={e.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5">
              <span className="hint w-24 flex-none">{when(e.ts)}</span>
              <Pill tone={e.kind.includes("failed") || e.kind.includes("error") ? "bad" : e.kind.includes("refused") || e.kind.includes("rejected") ? "warn" : e.kind.includes("created") ? "ok" : ""}>{nameOf(T.events, e.kind)}</Pill>
              {e.account_id && <Who id={e.account_id} hint={e.hint} identifier={e.identifier} />}
              <span className="sub min-w-0 flex-1 truncate" title={e.detail}>
                {e.detail}
              </span>
              <PlatformPill platform={e.platform} className="hide-sm" />
              <IpChip ip={e.ip} className="hide-sm" />
            </div>
          ))}
          {!events.length && !loading && <div className="hint py-8 text-center">{T.g.none}</div>}
        </div>
        <div className="flex items-center gap-3 px-4 py-2">
          {!done && events.length > 0 && (
            <Btn size="sm" onClick={() => load(events[events.length - 1].id)} disabled={loading}>
              {T.at.more}
            </Btn>
          )}
          {loading && <span className="hint pulse">{T.g.loading}</span>}
          <span className="hint">{fmt(events.length)} · {dateOf(events[events.length - 1]?.ts)}</span>
        </div>
      </Panel>
    </>
  );
}
