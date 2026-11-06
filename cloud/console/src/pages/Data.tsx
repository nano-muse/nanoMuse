/** "Help improve" in aggregate and the latest kept turns, the export, and conversation
 *  sync's counts. */

import type { PageProps } from "../App";
import { download } from "../lib/api";
import { bytes, compact, dateOf, fmt, nowS } from "../lib/format";
import { useData } from "../lib/hooks";
import { nameOf, useT } from "../lib/i18n";
import { hashOf } from "../lib/router";
import type { ClientEventsSummary, DataView, Deletions, Overview, RecordView, Sync } from "../lib/types";
import { Bars, Legend, Ranks, modelColor, platformColor } from "../ui/charts";
import { Btn, DataTable, Grid, Kpi, Kpis, Note, Panel, Pill, useToast } from "../ui/primitives";
import { Ago, Who } from "../ui/who";
import { Loaded, dayLabels, dayTitles } from "./common";
import { SampleCard } from "./SampleCard";

export function Data({ days }: PageProps) {
  const T = useT();
  const toast = useToast();
  const q = useData<DataView>(`/v1/admin/data?days=${days}`, { poll: 120_000 });
  const sy = useData<Sync>("/v1/admin/sync", { poll: 300_000 });
  const re = useData<RecordView>(`/v1/admin/record?days=${days}`, { poll: 300_000 });
  const ev = useData<ClientEventsSummary>(`/v1/admin/client-events/summary?days=${days}`, { poll: 300_000 });
  const de = useData<Deletions>("/v1/admin/deletions", { poll: 600_000 });
  const ov = useData<Overview>("/v1/admin/overview?days=7", { maxAge: 300_000 });
  const offsetH = Number(ov.data?.settings.day_offset_h || 0);
  const expEvents = (since: number) => download(`/v1/admin/client-events/export?since=${since}`, `nanomuse-client-events-${since}.jsonl`).catch((e) => toast(String(e.message || e), "bad"));
  const exp = (since: number) => download(`/v1/admin/samples/export?since=${since}`, `nanomuse-samples-${since}.jsonl`).catch((e) => toast(String(e.message || e), "bad"));
  const expRecord = (since: number) => download(`/v1/admin/turns/export?since=${since}`, `nanomuse-turns-${since}.jsonl`).catch((e) => toast(String(e.message || e), "bad"));
  return (
    <>
      <Loaded q={q}>
        {(d) => (
          <>
            <Kpis>
              <Kpi label={T.da.on} value={fmt(d.accounts.on)} sub={T.da.onSub(d.accounts.on, d.accounts.total)} tone="ok" />
              <Kpi label={T.da.off} value={fmt(d.accounts.turned_off_ever)} sub={T.da.offSub} />
              <Kpi label={T.da.turns} value={fmt(d.period.turns)} sub={T.da.turnsSub(d.totals.turns, d.accounts.with_samples)} tone="accent" />
              <Kpi label={T.da.calls} value={fmt(d.period.samples)} sub={T.da.callsSub(d.totals.samples, d.period.turns ? (d.period.samples / d.period.turns).toFixed(1) : "–")} />
              <Kpi label={T.da.tokens} value={compact(d.period.prompt_tokens + d.period.completion_tokens)} sub={T.da.tokensSub(compact(d.totals.prompt_tokens), compact(d.totals.completion_tokens))} />
              <Kpi label={T.g.accounts} value={fmt(d.period.accounts)} sub={T.g.period(days)} />
              <Kpi label={T.g.share} value={`${(100 * d.accounts.share).toFixed(0)}%`} sub={T.da.defaultOn(d.default_on)} small />
            </Kpis>
            <Note>
              <b>{T.da.kept}:</b> {d.keeps.kept.join(", ")}. <b>{T.da.notKept}:</b> {d.keeps.not_kept.join(", ")}.
            </Note>
            <Note>
              {T.da.twoWays} {d.totals.turns_pending > 0 && <span className="text-warn">{T.da.pendingTurns(d.totals.turns_pending)}</span>} <a className="text-accent" href={hashOf("turns")}>{T.da.reBrowse} →</a>
            </Note>
            <Panel
              title={T.da.series}
              right={
                <>
                  <Btn size="sm" onClick={() => exp(nowS() - days * 86400)}>{T.da.exportSince(days)}</Btn>
                  <Btn size="sm" onClick={() => exp(0)}>{T.da.export}</Btn>
                  <span className="hint">{T.da.exportNote}</span>
                </>
              }
            >
              <Bars
                series={[
                  { name: T.da.legend.samples, values: d.days.map((x) => x.samples), color: "var(--c1)" },
                  { name: T.da.legend.turns, values: d.days.map((x) => x.turns), color: "var(--c2)" },
                ]}
                lines={[
                  { name: T.da.legend.turned_on, values: d.days.map((x) => x.turned_on), color: "var(--ok)" },
                  { name: T.da.legend.turned_off, values: d.days.map((x) => x.turned_off), color: "var(--bad)" },
                ]}
                labels={dayLabels(d.days.map((x) => x.day), offsetH)}
                titles={dayTitles(d.days.map((x) => x.day), offsetH)}
                height={150}
              />
              <Legend className="mt-2" items={[{ name: T.da.legend.samples, color: "var(--c1)" }, { name: T.da.legend.turns, color: "var(--c2)" }, { name: T.da.legend.turned_on, color: "var(--ok)" }, { name: T.da.legend.turned_off, color: "var(--bad)" }]} />
            </Panel>
            <Grid cols={2}>
              <Panel title={T.da.byRun}>
                <Ranks rows={d.by_run.map((r) => ({ name: nameOf(T.da.runs, r.run || "unsaid"), value: r.turns, sub: T.da.both(r.turns, r.samples), color: r.run === "person" || r.run === "" ? "var(--c1)" : "var(--c3)" }))} showShare />
              </Panel>
              <Panel title={T.da.bySource}>
                <Ranks rows={d.by_source.map((r) => ({ name: nameOf(T.da.sources, r.source), value: r.turns, sub: T.da.both(r.turns, r.samples), color: r.source === "own" ? "var(--c4)" : "var(--c2)" }))} showShare />
              </Panel>
            </Grid>
            <Grid cols={3}>
              <Panel title={T.da.byModel}>
                <Ranks rows={d.by_model.map((m) => ({ name: <code>{m.model}</code>, value: m.turns, sub: `${T.da.both(m.turns, m.samples)} · ${compact(m.tokens)} ${T.g.tokens}`, color: modelColor(m.model) }))} showShare />
              </Panel>
              <Panel title={T.da.byPlatform}>
                <Ranks rows={d.by_platform.map((p) => ({ name: nameOf(T.platforms, p.platform), value: p.turns, sub: T.da.both(p.turns, p.samples), color: platformColor(p.platform) }))} showShare />
              </Panel>
              <Panel title={T.da.byAccount} pad={false}>
                <DataTable
                  rows={d.by_account}
                  rowKey={(a) => a.account_id}
                  defaultSort="turns"
                  limit={12}
                  columns={[
                    { key: "who", label: T.da.accCols.who, sortable: false, render: (a) => <Who id={a.account_id} hint={a.hint} channel={a.channel} tags={!a.contribute ? <Pill tone="warn">{T.g.off}</Pill> : null} /> },
                    { key: "turns", label: T.da.accCols.turns, num: true, render: (a) => fmt(a.turns) },
                    { key: "samples", label: T.da.accCols.samples, num: true, render: (a) => fmt(a.samples) },
                    { key: "tokens", label: T.da.accCols.tokens, num: true, value: (a) => a.prompt_tokens + a.completion_tokens, render: (a) => compact(a.prompt_tokens + a.completion_tokens) },
                    { key: "last_ts", label: T.da.accCols.last, num: true, render: (a) => <Ago ts={a.last_ts} /> },
                  ]}
                />
              </Panel>
            </Grid>
            <Panel title={T.da.recent}>
              <div className="flex flex-col gap-2">
                {d.recent.map((s) => (
                  <SampleCard key={s.id} s={s} withWho />
                ))}
                {!d.recent.length && <div className="hint py-6 text-center">{T.g.none}</div>}
              </div>
            </Panel>
          </>
        )}
      </Loaded>
      <Loaded q={re} title={T.da.reTitle}>
        {(r) => (
          <Panel
            title={T.da.reTitle}
            sub={r.on ? T.da.reNote : T.da.reOff}
            right={
              r.on ? (
                <>
                  <Btn size="sm" onClick={() => expRecord(nowS() - days * 86400)}>{T.da.reExportSince(days)}</Btn>
                  <Btn size="sm" onClick={() => expRecord(0)}>{T.da.reExport}</Btn>
                  <span className="hint">{T.da.reExportNote}</span>
                </>
              ) : null
            }
          >
            {r.on && (
              <>
                <Kpis>
                  <Kpi flat label={T.da.reQuestions} value={fmt(r.period.questions)} sub={T.da.reQuestionsSub(r.questions.calls_mean ? r.questions.calls_mean.toFixed(1) : "–")} tone="accent" onClick={() => (location.hash = hashOf("turns"))} />
                  <Kpi flat label={T.da.reTurns} value={fmt(r.period.n)} sub={T.da.reTurnsSub(r.totals.n, r.totals.accounts)} />
                  <Kpi flat label={T.da.reWithMedia} value={fmt(r.questions.with_media)} sub={T.da.reWithHands + " " + fmt(r.questions.with_hands)} />
                  {r.questions.pending > 0 && <Kpi flat label={T.da.rePending} value={fmt(r.questions.pending)} sub={T.da.rePendingSub} tone="warn" />}
                  <Kpi flat label={T.g.accounts} value={fmt(r.period.accounts)} sub={T.g.period(days)} />
                  <Kpi flat label={T.da.reOwn} value={fmt(r.totals.own)} sub={T.da.reOwnSub} />
                  <Kpi flat label={T.da.rePartial} value={fmt(r.totals.partial)} />
                  <Kpi flat label={T.da.reFiles} value={fmt(r.totals.files)} sub={T.da.reFilesSub(r.totals.media)} />
                  <Kpi flat label={T.da.reStore} value={bytes(r.totals.store_bytes)} sub={T.da.reStoreSub(bytes(r.media_cap_bytes))} tone={r.totals.store_bytes > 0.9 * r.media_cap_bytes ? "warn" : undefined} />
                  <Kpi flat label={T.g.day} value={T.da.reKeep(r.keep_days)} small />
                </Kpis>
                <Bars
                  series={[
                    { name: T.da.reLegend.turns, values: r.days.map((x) => x.turns), color: "var(--c2)" },
                    { name: T.da.reLegend.questions, values: r.days.map((x) => x.questions), color: "var(--c1)" },
                  ]}
                  lines={[{ name: T.da.reLegend.media, values: r.days.map((x) => x.media), color: "var(--c4)" }]}
                  labels={dayLabels(r.days.map((x) => x.day), offsetH)}
                  titles={dayTitles(r.days.map((x) => x.day), offsetH)}
                  height={120}
                />
                <Legend className="mt-2" items={[{ name: T.da.reLegend.turns, color: "var(--c2)" }, { name: T.da.reLegend.questions, color: "var(--c1)" }, { name: T.da.reLegend.media, color: "var(--c4)" }]} />
                {Object.keys(r.questions.calls_per_question || {}).length > 0 && (
                  <div className="mt-3">
                    <div className="hint mb-1">{T.da.rePerQuestion}</div>
                    <Ranks rows={Object.entries(r.questions.calls_per_question).map(([b, n]) => ({ name: T.da.reBucket(b), value: n, color: b === "1" ? "var(--c1)" : "var(--c3)" }))} showShare />
                  </div>
                )}
              </>
            )}
          </Panel>
        )}
      </Loaded>
      <Loaded q={ev} title={T.da.evTitle}>
        {(e) => {
          const kinds = Object.entries(e.kinds).sort((a, b) => b[1] - a[1]);
          const facets = Object.entries(e.facets).flatMap(([kind, keys]) => Object.entries(keys).map(([key, split]) => ({ kind, key, split })));
          return (
            <Panel
              title={T.da.evTitle}
              sub={T.da.evNote}
              right={
                <>
                  <Btn size="sm" onClick={() => expEvents(nowS() - days * 86400)}>{T.da.evExportSince(days)}</Btn>
                  <Btn size="sm" onClick={() => expEvents(0)}>{T.da.evExport}</Btn>
                  <span className="hint">{T.da.evExportNote}</span>
                </>
              }
            >
              <Kpis>
                <Kpi flat label={T.da.evTotal} value={fmt(e.total)} sub={T.da.evTotalSub(e.accounts)} />
                {kinds.slice(0, 5).map(([k, n]) => (
                  <Kpi key={k} flat label={nameOf(T.da.evKinds, k)} value={fmt(n)} small />
                ))}
              </Kpis>
              <Grid cols={3}>
                <Panel title={T.da.evByKind}>
                  <Ranks rows={kinds.map(([k, n]) => ({ name: nameOf(T.da.evKinds, k), value: n, color: "var(--c3)" }))} showShare />
                </Panel>
                {facets.map((f) => (
                  <Panel key={`${f.kind}.${f.key}`} title={`${nameOf(T.da.evKinds, f.kind)} · ${nameOf(T.da.evFacet, f.key)}`}>
                    <Ranks
                      rows={Object.entries(f.split)
                        .sort((a, b) => b[1] - a[1])
                        .map(([code, n]) => ({ name: nameOf(T.da.evCodes, code), value: n, color: code === "deny" || code === "down" || code === "false" || code === "failed" ? "var(--bad)" : code === "ask" ? "var(--warn)" : "var(--ok)" }))}
                      showShare
                    />
                  </Panel>
                ))}
              </Grid>
              {!e.total && <div className="hint py-6 text-center">{T.g.none}</div>}
            </Panel>
          );
        }}
      </Loaded>
      <Loaded q={de} title={T.da.deTitle}>
        {(l) => (
          <Panel
            title={T.da.deTitle}
            sub={T.da.deNote}
            right={
              <Btn size="sm" onClick={() => download("/v1/admin/deletions", "nanomuse-deletions.json").catch((e) => toast(String(e.message || e), "bad"))}>
                {T.da.deExport}
              </Btn>
            }
          >
            <Kpis>
              <Kpi flat label={T.da.deTitle} value={fmt(l.deletions.length)} sub={T.da.deCount(l.deletions.length)} />
              <Kpi flat label={nameOf(T.da.deScope, "samples")} value={fmt(l.deletions.filter((x) => x.scope === "samples").length)} small />
              <Kpi flat label={nameOf(T.da.deScope, "account")} value={fmt(l.deletions.filter((x) => x.scope === "account").length)} small />
              <Kpi flat label={T.g.day} value={l.deletions.length ? dateOf(l.deletions[l.deletions.length - 1].ts) : "–"} small />
            </Kpis>
          </Panel>
        )}
      </Loaded>
      <Loaded q={sy} title={T.da.syTitle}>
        {(s) => (
          <Panel title={T.da.syTitle} sub={T.da.syNote}>
            <Kpis>
              <Kpi flat label={T.da.syOn} value={fmt(s.accounts_enabled)} sub={T.da.syOnSub(s.accounts_disabled)} />
              <Kpi flat label={T.da.syWith} value={fmt(s.accounts_with_data)} />
              <Kpi flat label={T.da.syConvs} value={fmt(s.conversations)} sub={`${T.g.limit} ${fmt(s.limits.conversations)}`} />
              <Kpi flat label={T.da.syMsgs} value={fmt(s.messages)} sub={T.da.syMsgsSub(s.limits.messages)} />
              <Kpi flat label={T.da.syBytes} value={bytes(s.bytes)} />
              <Kpi flat label={T.g.day} value={dateOf(nowS())} small />
            </Kpis>
          </Panel>
        )}
      </Loaded>
    </>
  );
}
