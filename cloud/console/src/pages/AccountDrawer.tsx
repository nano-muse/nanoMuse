/** One account in full, over any page: identity, pool and actions, usage, addresses,
 *  sessions, devices, the statement and the timeline (paged and filtered), the people it
 *  invited (and the reclaim), its kept turns, its showcase record. */

import { useCallback, useEffect, useRef, useState } from "react";
import { errorText } from "../App";
import { ApiError, download, get, post, qs } from "../lib/api";
import { LatestRequest } from "../lib/latest-request";
import { clientLine } from "../lib/client";
import { compact, dateOf, dur, fmt, money, ms, when } from "../lib/format";
import { invalidate, useData, useNow } from "../lib/hooks";
import { nameOf, useT, useZh } from "../lib/i18n";
import { hashOf, useRoute } from "../lib/router";
import type { AccountDetail, EventRow, LedgerRow, Sample } from "../lib/types";
import { Bars, Legend, modelColor } from "../ui/charts";
import { Bar, Btn, DataTable, Drawer, Failed, KV, Loading, Note, Panel, Pill, Search, Tabs, useDialog, useToast, type Col } from "../ui/primitives";
import { Ago, IpChip, PlatformPill, Who, identOf, shortId } from "../ui/who";
import { KindRanks, ModelRanks } from "./common";
import { SampleCard } from "./SampleCard";

type Tab = "overview" | "usage" | "addresses" | "sessions" | "devices" | "ledger" | "events" | "invited" | "samples" | "demo";

export function AccountDrawer({ id, days, onClose }: { id: string; days: number; onClose: () => void }) {
  const T = useT();
  const route = useRoute();
  const tab = (route.params.get("tab") || "overview") as Tab;
  const q = useData<AccountDetail>(`/v1/admin/accounts/${encodeURIComponent(id)}?days=${days}`, { maxAge: 5000 });
  const a = q.data?.account;
  const setTab = (t: Tab) => route.set({ tab: t === "overview" ? null : t }, true);
  const name = a ? identOf(a.id, a.hint, a.identifier) : shortId(id);
  const tabs: { id: Tab; label: string; n?: number }[] = [
    { id: "overview", label: T.ac.tabs.overview },
    { id: "usage", label: T.ac.tabs.usage },
    { id: "ledger", label: T.ac.tabs.ledger, n: q.data?.ledger_total },
    { id: "events", label: T.ac.tabs.events, n: q.data?.events_total },
    { id: "addresses", label: T.ac.tabs.addresses, n: q.data?.addresses.length },
    { id: "sessions", label: T.ac.tabs.sessions, n: q.data?.sessions.length },
    { id: "devices", label: T.ac.tabs.devices, n: q.data?.devices.length },
    { id: "invited", label: T.ac.tabs.invited, n: a?.invited_total },
    { id: "samples", label: T.ac.tabs.samples, n: a?.samples },
    { id: "demo", label: T.ac.tabs.demo, n: q.data?.demo?.visits_total },
  ];
  return (
    <Drawer
      title={
        <span className="inline-flex items-center gap-2">
          {name}
          {a?.member && <Pill tone="violet">{T.pe.tags.member}</Pill>}
          {a?.disabled && <Pill tone="bad">{T.pe.tags.disabled}</Pill>}
          {a?.locked && <Pill tone="warn">{T.pe.tags.locked}</Pill>}
          {a?.review && <Pill tone="cyan">{T.ac.reviewTag}</Pill>}
        </span>
      }
      sub={
        <span className="inline-flex items-center gap-2">
          <code>{id}</code>
          {a && <span>· {nameOf(T.channels, a.channel)}</span>}
          {a && <span>· {T.ac.created} {dateOf(a.created_at)}</span>}
        </span>
      }
      onClose={onClose}
      width={860}
    >
      {q.error && !q.data ? (
        <Failed error={q.error.status === 404 ? T.ac.notFound : errorText(q.error)} onRetry={() => void q.reload()} />
      ) : !q.data ? (
        <Loading />
      ) : (
        <div className="flex flex-col gap-3">
          <Tabs tabs={tabs} value={tab} onChange={setTab} />
          {tab === "overview" && <OverviewTab d={q.data} reload={q.reload} onClose={onClose} />}
          {tab === "usage" && <UsageTab d={q.data} />}
          {tab === "addresses" && <AddressesTab d={q.data} />}
          {tab === "sessions" && <SessionsTab d={q.data} />}
          {tab === "devices" && <DevicesTab d={q.data} />}
          {tab === "ledger" && <LedgerTab id={id} total={q.data.ledger_total} />}
          {tab === "events" && <EventsTab id={id} total={q.data.events_total} />}
          {tab === "invited" && <InvitedTab d={q.data} reload={q.reload} />}
          {tab === "samples" && <SamplesTab id={id} total={q.data.account.samples} />}
          {tab === "demo" && <DemoTab d={q.data} />}
        </div>
      )}
    </Drawer>
  );
}

function OverviewTab({ d, reload, onClose }: { d: AccountDetail; reload: () => Promise<void>; onClose: () => void }) {
  const T = useT();
  const zh = useZh();
  const now = useNow(60_000);
  const dialog = useDialog();
  const toast = useToast();
  const a = d.account;
  const who = identOf(a.id, a.hint, a.identifier);
  const [busy, setBusy] = useState(false);
  const act = async (fn: () => Promise<unknown>, done?: string) => {
    setBusy(true);
    try {
      await fn();
      toast(done || T.ac.changed, "ok");
      invalidate("/v1/admin/accounts", "/v1/admin/overview", "/v1/admin/invites");
      await reload();
    } catch (e) {
      toast(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e), "bad");
    } finally {
      setBusy(false);
    }
  };
  const grant = async () => {
    const r = await dialog({ title: T.ac.grantTokens, fields: [{ id: "tokens", label: T.ac.grantPrompt, type: "number", step: "1" }] });
    if (!r || !Number(r.tokens)) return;
    await act(() => post("/v1/admin/grant", { account_id: a.id, tokens: Math.round(Number(r.tokens)) }));
  };
  const credit = async () => {
    const r = await dialog({ title: T.ac.credit, fields: [{ id: "cny", label: T.ac.creditPrompt, type: "number", step: "0.01" }, { id: "note", label: T.ac.note, type: "text" }] });
    if (!r || !Number(r.cny)) return;
    await act(() => post("/v1/admin/credit", { account_id: a.id, cny: Number(r.cny), note: String(r.note || "") }));
  };
  const setPool = async () => {
    const r = await dialog({
      title: T.ac.setPool,
      fields: [
        { id: "mode", label: T.ac.setPool, type: "select", value: "left_cny", options: Object.entries(T.ac.poolMode).map(([id, label]) => ({ id, label })) },
        { id: "cny", label: T.ac.poolPrompt, type: "number", step: "0.01", value: String(a.left_cny ?? "") },
        { id: "note", label: T.ac.note, type: "text" },
      ],
    });
    if (!r || r.cny === "" || !Number.isFinite(Number(r.cny))) return;
    await act(() => post("/v1/admin/pool", { account_id: a.id, [String(r.mode)]: Number(r.cny), note: String(r.note || "") }));
  };
  const member = async () => {
    const on = !a.unlimited;
    if (!(await dialog({ title: on ? T.ac.makeMember : T.ac.unmakeMember, body: T.ac.confirmMember(who, on) }))) return;
    await act(() => post("/v1/admin/unlimited", { account_id: a.id, unlimited: on }));
  };
  const disable = async () => {
    const on = !a.disabled;
    if (!(await dialog({ title: on ? T.ac.disable : T.ac.enable, body: on ? T.ac.confirmDisable(who) : T.ac.confirmEnable(who), danger: on }))) return;
    await act(() => post("/v1/admin/disable", { account_id: a.id, disabled: on }));
  };
  const remove = async () => {
    if (!(await dialog({ title: T.ac.remove, body: T.ac.confirmDelete(who), danger: true, okLabel: T.g.delete }))) return;
    try {
      await post("/v1/admin/delete", { account_id: a.id });
      toast(T.g.done, "ok");
      invalidate("/v1/admin/accounts", "/v1/admin/overview", "/v1/admin/invites");
      onClose();
    } catch (e) {
      toast(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e), "bad");
    }
  };
  const c = d.calls;
  const sp = d.spend;
  const cap = a.member ? 0 : Number(sp.grant_cny || 0);
  return (
    <>
      <div className="grid gap-3 lg:grid-cols-2">
        <Panel title={T.ac.identity}>
          <KV
            rows={[
              [T.ac.id, <code>{a.id}</code>],
              [T.ac.channel, `${nameOf(T.channels, a.channel)} · ${a.identifier || a.hint}`],
              [T.ac.created, `${dateOf(a.created_at)} (${dur(now - a.created_at, zh)})`],
              [T.ac.lastSeen, <Ago ts={a.last_seen_at} />],
              [T.ac.client, <span>{clientLine(a.last_ua)} <PlatformPill platform={a.last_platform} version={a.last_version} /></span>],
              [T.ac.firstIp, <IpChip ip={a.first_ip} />],
              [T.ac.lastIp, <IpChip ip={a.last_ip} />],
              [T.ac.inviteCode, <code>{a.invite_code || "·"}</code>],
              [T.ac.invitedBy, a.inviter ? <Who id={a.inviter.id} hint={a.inviter.hint} /> : a.invited_by ? <code>{a.invited_by}</code> : "·"],
              [T.ac.invites, `${fmt(a.invited_total || a.invites || 0)} · ${T.ac.inviteEarned(money(a.invite_earned_cny))}`],
              [T.ac.password, a.has_password ? <span>{T.g.yes}{a.locked ? ` · ${T.ac.locked}` : ""}{a.failed_logins ? ` · ${T.ac.failedLogins(a.failed_logins)}` : ""}</span> : T.g.no],
              [T.ac.contribute, <span>{a.contribute ? T.g.on : T.g.off} · {T.ac.samples} {fmt(a.samples)}</span>],
              [T.ac.sync, a.sync_enabled ? T.g.on : T.g.off],
            ]}
          />
        </Panel>
        <div className="flex flex-col gap-3">
          <Panel title={T.ac.spend} sub={a.member ? T.ac.unlimited : T.pe.poolLine(money(sp.left_cny), money(sp.grant_cny))}>
            <div className="grid grid-cols-3 gap-2">
              <div className="kpi"><div className="hint">{T.ac.today}</div><div className="v sm">{money(sp.today_cny)}</div></div>
              <div className="kpi"><div className="hint">{T.ac.total}</div><div className="v sm">{money(sp.total_cny)}</div></div>
              <div className="kpi"><div className="hint">{T.g.requests}</div><div className="v sm">{fmt(sp.requests_total)}</div></div>
            </div>
            {!a.member && <Bar value={Math.max(0, cap - Number(sp.left_cny || 0))} max={cap || 1} tone={Number(sp.left_cny) <= 0 ? "bad" : "accent"} className="mt-3" />}
            <div className="mt-3 flex flex-wrap gap-2">
              <Btn size="sm" onClick={credit} disabled={busy}>{T.ac.credit}</Btn>
              <Btn size="sm" onClick={setPool} disabled={busy}>{T.ac.setPool}</Btn>
              <Btn size="sm" onClick={grant} disabled={busy}>{T.ac.grantTokens}</Btn>
              <Btn size="sm" onClick={member} disabled={busy}>{a.unlimited ? T.ac.unmakeMember : T.ac.makeMember}</Btn>
              <Btn size="sm" variant={a.disabled ? "" : "danger"} onClick={disable} disabled={busy}>{a.disabled ? T.ac.enable : T.ac.disable}</Btn>
              <Btn size="sm" variant="danger" onClick={remove} disabled={busy}>{T.ac.remove}</Btn>
            </div>
          </Panel>
          <Panel title={T.ac.calls} sub={c.last_ts ? <Ago ts={c.last_ts} /> : T.g.none}>
            {c.n ? (
              <>
                <div>{T.ac.callsLine(c.ok, c.n, ms(c.avg_ttft_ms), ms(c.avg_total_ms))}</div>
                <div className="sub">{T.ac.callsFlags(c.hands, c.images, c.with_tools, c.refused)} · {T.g.errors} {c.errors} · {T.g.wait} {ms(c.avg_wait_ms)}</div>
              </>
            ) : (
              <div className="hint">·</div>
            )}
          </Panel>
        </div>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <Panel title={`${T.ac.byKind} · ${T.g.today}`}>
          <KindRanks rows={d.usage.today.by_kind} />
          <div className="hint mt-3 mb-1">{T.g.period(d.usage.period.days)}</div>
          <KindRanks rows={d.usage.period.by_kind} />
        </Panel>
        <Panel title={`${T.ac.byModel} · ${T.g.period(d.usage.period.days)}`}>
          <ModelRanks rows={d.usage.period.by_model} />
        </Panel>
      </div>
      <Panel title={T.ac.tabs.events} pad={false}>
        <EventsTable rows={d.events} />
      </Panel>
    </>
  );
}

function UsageTab({ d }: { d: AccountDetail }) {
  const T = useT();
  const byDay = d.usage.period.by_day;
  const daysSet = [...new Set(byDay.map((r) => r.day))].sort();
  const kinds = [...new Set(byDay.map((r) => r.kind))];
  return (
    <>
      <Panel title={`${T.ac.byDay} · ${T.g.period(d.usage.period.days)}`}>
        <Bars
          series={kinds.map((k, i) => ({ name: nameOf(T.kinds, k), values: daysSet.map((day) => byDay.filter((r) => r.day === day && r.kind === k).reduce((a, r) => a + r.cost_cny, 0)), color: `var(--c${(i % 8) + 1})` }))}
          labels={daysSet.map((x) => dateOf(x).slice(5))}
          titles={daysSet.map((x) => `${dateOf(x)} · ${fmt(byDay.filter((r) => r.day === x).reduce((a, r) => a + r.requests, 0))} ${T.g.requests}`)}
          format={(v) => money(v)}
          height={150}
        />
        <Legend className="mt-2" items={kinds.map((k, i) => ({ name: nameOf(T.kinds, k), color: `var(--c${(i % 8) + 1})` }))} />
      </Panel>
      <div className="grid gap-3 lg:grid-cols-2">
        <Panel title={T.ac.byModel}><ModelRanks rows={d.usage.period.by_model} /></Panel>
        <Panel title={`${T.ac.byKind} · ${T.ac.total}`}><KindRanks rows={d.usage.total.by_kind} /></Panel>
      </div>
      <Panel title={T.ac.tabs.ledger} sub={T.g.last} pad={false}>
        <LedgerTable rows={d.recent} />
      </Panel>
    </>
  );
}

function AddressesTab({ d }: { d: AccountDetail }) {
  const T = useT();
  return (
    <Panel pad={false}>
      <DataTable
        rows={d.addresses}
        rowKey={(r) => r.ip}
        defaultSort="last_seen"
        empty={T.ac.noAddresses}
        columns={[
          { key: "ip", label: T.ac.addrCols.ip, render: (r) => <IpChip ip={r.ip} /> },
          { key: "n", label: T.ac.addrCols.n, num: true, render: (r) => fmt(r.n) },
          { key: "first_seen", label: T.ac.addrCols.first, num: true, render: (r) => when(r.first_seen) },
          { key: "last_seen", label: T.ac.addrCols.last, num: true, render: (r) => <Ago ts={r.last_seen} /> },
          { key: "platforms", label: T.ac.addrCols.platforms, sortable: false, render: (r) => <span className="inline-flex gap-1">{r.platforms.map((p) => <PlatformPill key={p} platform={p} />)}</span> },
        ]}
      />
    </Panel>
  );
}

function SessionsTab({ d }: { d: AccountDetail }) {
  const T = useT();
  return (
    <Panel pad={false}>
      <DataTable
        rows={d.sessions}
        rowKey={(s) => s.prefix + s.created_at}
        defaultSort="last_used_at"
        empty={T.ac.noSessions}
        columns={[
          { key: "prefix", label: T.ac.sesCols.prefix, render: (s) => <code>{s.prefix}</code> },
          { key: "device", label: T.ac.sesCols.device, render: (s) => s.device || "·" },
          { key: "via", label: T.ac.sesCols.via },
          { key: "created_at", label: T.ac.sesCols.created, num: true, render: (s) => when(s.created_at) },
          { key: "last_used_at", label: T.ac.sesCols.last, num: true, render: (s) => <Ago ts={s.last_used_at} /> },
          { key: "revoked_at", label: T.ac.sesCols.revoked, render: (s) => (s.revoked_at ? <Pill tone="bad">{when(s.revoked_at)}</Pill> : <Pill tone="ok">{T.g.active}</Pill>) },
          { key: "ip", label: T.ac.sesCols.ip, render: (s) => <IpChip ip={s.ip} /> },
          { key: "client", label: T.ac.sesCols.client, sortable: false, render: (s) => <span title={s.ua}><PlatformPill platform={s.platform} version={s.version} /></span> },
        ]}
      />
    </Panel>
  );
}

function DevicesTab({ d }: { d: AccountDetail }) {
  const T = useT();
  return (
    <Panel pad={false}>
      <DataTable
        rows={d.devices}
        rowKey={(x) => x.id}
        defaultSort="last_seen"
        empty={T.ac.noDevices}
        columns={[
          { key: "name", label: T.ac.devCols.name, render: (x) => <span>{x.name || <code>{x.id.slice(0, 8)}</code>}</span> },
          { key: "kind", label: T.ac.devCols.kind },
          { key: "os", label: T.ac.devCols.os, render: (x) => x.os || "·" },
          { key: "version", label: T.ac.devCols.version, render: (x) => x.version || "·" },
          { key: "online", label: T.ac.devCols.online, render: (x) => (x.online ? <Pill tone="ok">{T.g.online}</Pill> : <span className="hint">·</span>) },
          { key: "last_seen", label: T.ac.devCols.last, num: true, render: (x) => <Ago ts={x.last_seen} /> },
          { key: "llm", label: T.ac.devCols.llm, render: (x) => (x.llm_provider ? <code>{x.llm_provider}{x.llm_model ? ` / ${x.llm_model}` : ""}</code> : <span className="hint">·</span>) },
          { key: "actions", label: T.ac.devCols.actions, sortable: false, wrap: true, render: (x) => <span className="hint">{(x.actions || []).join(", ")}</span> },
        ]}
      />
    </Panel>
  );
}

function LedgerTable({ rows }: { rows: LedgerRow[] }) {
  const T = useT();
  const cols: Col<LedgerRow>[] = [
    { key: "ts", label: T.ac.ledCols.time, render: (r) => when(r.ts) },
    { key: "kind", label: T.ac.ledCols.kind, render: (r) => <Pill tone={r.kind === "credit" || r.kind === "grant" ? "ok" : ""}>{nameOf(T.kinds, r.kind)}</Pill> },
    { key: "model", label: T.ac.ledCols.model, render: (r) => <code style={{ color: r.model ? modelColor(r.model) : undefined }}>{r.model || "·"}</code> },
    { key: "prompt_tokens", label: T.ac.ledCols.in, num: true, render: (r) => compact(r.prompt_tokens) },
    { key: "completion_tokens", label: T.ac.ledCols.out, num: true, render: (r) => compact(r.completion_tokens) },
    { key: "charged", label: T.ac.ledCols.charged, num: true, render: (r) => compact(r.charged) },
    { key: "cost_cny", label: T.ac.ledCols.cost, num: true, render: (r) => money(r.cost_cny, 4) },
    { key: "ip", label: T.ac.ledCols.ip, render: (r) => <span className="inline-flex items-center gap-1"><IpChip ip={r.ip} /><PlatformPill platform={r.platform} /></span> },
  ];
  return <DataTable rows={rows} rowKey={(r) => r.id} columns={cols} />;
}

function EventsTable({ rows }: { rows: EventRow[] }) {
  const T = useT();
  const cols: Col<EventRow>[] = [
    { key: "ts", label: T.ac.evCols.time, render: (r) => when(r.ts) },
    { key: "kind", label: T.ac.evCols.kind, render: (r) => <Pill tone={r.kind.includes("failed") || r.kind.includes("error") ? "bad" : r.kind.includes("refused") || r.kind.includes("rejected") ? "warn" : ""}>{nameOf(T.events, r.kind)}</Pill> },
    { key: "detail", label: T.ac.evCols.detail, wrap: true, sortable: false, render: (r) => <span className="inline-block max-w-[360px] truncate align-middle" title={r.detail}>{r.detail}</span> },
    { key: "ip", label: T.ac.evCols.ip, render: (r) => <IpChip ip={r.ip} /> },
    { key: "client", label: T.ac.evCols.client, sortable: false, render: (r) => <PlatformPill platform={r.platform} /> },
  ];
  return <DataTable rows={rows} rowKey={(r) => r.id} columns={cols} />;
}

/** A paged list from `/v1/admin/accounts/{id}/{ledger|events}` with kind and text filters. */
function usePaged<R extends { id: number }>(path: string, kind: string, text: string) {
  const [rows, setRows] = useState<R[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  // a page asked for under older filters (a "More" still in flight when they changed)
  // must not land under the new ones, nor clear their loading flag
  const requests = useRef(new LatestRequest());
  const load = useCallback(
    (before: number) => requests.current.run(
      () => get<{ rows: R[]; total: number }>(`${path}${qs({ limit: 200, before, kind, q: text })}`),
      {
        start: () => { setLoading(true); setError(""); },
        success: (r) => {
          setRows((xs) => (before ? [...xs, ...r.rows] : r.rows));
          setTotal(r.total);
          setDone(r.rows.length < 200);
        },
        error: (e) => setError(e instanceof Error ? e.message : String(e)),
        finish: () => setLoading(false),
      },
    ),
    [path, kind, text],
  );
  useEffect(() => {
    const pending = requests.current;
    setRows([]);
    void load(0);
    return () => pending.invalidate();
  }, [load]);
  const more = () => rows.length && void load(rows[rows.length - 1].id);
  return { rows, total, loading, error, done, more };
}

function LedgerTab({ id, total: all }: { id: string; total: number }) {
  const T = useT();
  const route = useRoute();
  const kind = route.params.get("lk") || "";
  const text = route.params.get("lq") || "";
  const [draft, setDraft] = useState(text);
  useEffect(() => setDraft(text), [text]);
  const pg = usePaged<LedgerRow>(`/v1/admin/accounts/${encodeURIComponent(id)}/ledger`, kind, text);
  return (
    <Panel
      right={
        <>
          <select className="inp" value={kind} onChange={(e) => route.set({ lk: e.target.value || null }, true)}>
            <option value="">{T.g.all}</option>
            {Object.entries(T.kinds).map(([k, l]) => (
              <option key={k} value={k}>
                {l}
              </option>
            ))}
          </select>
          <form onSubmit={(e) => { e.preventDefault(); route.set({ lq: draft || null }, true); }}>
            <Search value={draft} onChange={setDraft} placeholder={T.ac.filterText} className="w-56" />
          </form>
        </>
      }
      title={<span>{T.ac.tabs.ledger} <span className="hint font-normal">{T.ac.ofTotal(pg.rows.length, pg.total || all)}</span></span>}
      pad={false}
    >
      {pg.error && <Note tone="bad" className="m-3">{pg.error}</Note>}
      <LedgerTable rows={pg.rows} />
      <div className="flex items-center gap-3 px-3 py-2">
        {!pg.done && <Btn size="sm" onClick={pg.more} disabled={pg.loading}>{T.ac.loadMore}</Btn>}
        {pg.loading && <span className="hint pulse">{T.g.loading}</span>}
      </div>
    </Panel>
  );
}

function EventsTab({ id, total: all }: { id: string; total: number }) {
  const T = useT();
  const route = useRoute();
  const kind = route.params.get("ek") || "";
  const text = route.params.get("eq") || "";
  const [draft, setDraft] = useState(text);
  useEffect(() => setDraft(text), [text]);
  const pg = usePaged<EventRow>(`/v1/admin/accounts/${encodeURIComponent(id)}/events`, kind, text);
  const FILTERS: [string, string][] = [
    ["", ""],
    ["sign_in.code,sign_in.password,sign_in.session,sign_in.failed,account.created", "signIns"],
    ["budget.refused", "refusals"],
    ["upstream.error", "errors"],
    ["content.rejected", "contentChecks"],
    ["call.ended", "calls"],
    ["password.set,password.changed,password.cleared", "passwords"],
  ];
  return (
    <Panel
      right={
        <>
          <select className="inp" value={kind} onChange={(e) => route.set({ ek: e.target.value || null }, true)}>
            {FILTERS.map(([v, k]) => (
              <option key={v} value={v}>
                {T.evFilters[k]}
              </option>
            ))}
          </select>
          <form onSubmit={(e) => { e.preventDefault(); route.set({ eq: draft || null }, true); }}>
            <Search value={draft} onChange={setDraft} placeholder={T.ac.filterEvents} className="w-56" />
          </form>
        </>
      }
      title={<span>{T.ac.tabs.events} <span className="hint font-normal">{T.ac.ofTotal(pg.rows.length, pg.total || all)}</span></span>}
      pad={false}
    >
      {pg.error && <Note tone="bad" className="m-3">{pg.error}</Note>}
      <EventsTable rows={pg.rows} />
      <div className="flex items-center gap-3 px-3 py-2">
        {!pg.done && <Btn size="sm" onClick={pg.more} disabled={pg.loading}>{T.ac.loadMore}</Btn>}
        {pg.loading && <span className="hint pulse">{T.g.loading}</span>}
      </div>
    </Panel>
  );
}

function InvitedTab({ d, reload }: { d: AccountDetail; reload: () => Promise<void> }) {
  const T = useT();
  const dialog = useDialog();
  const toast = useToast();
  const a = d.account;
  const who = identOf(a.id, a.hint, a.identifier);
  const reclaim = async () => {
    const r = await dialog({
      title: T.ac.abuse,
      body: `${T.ac.abuseHint}\n\n${T.ac.abuseConfirm(who)}`,
      danger: true,
      fields: [
        { id: "disable", label: T.ac.abuseDisable, type: "checkbox", value: false },
        { id: "delete_unused", label: T.ac.abuseDelete, type: "checkbox", value: false },
      ],
    });
    if (!r) return;
    try {
      const out = await post<{ reclaimed_cny: number; disabled: boolean; deleted: number; kept: number }>("/v1/admin/invites/abuse", { account_id: a.id, disable: !!r.disable, delete_unused: !!r.delete_unused });
      toast(T.ac.abuseResult(money(out.reclaimed_cny), out.disabled, out.deleted, out.kept), "ok");
      invalidate("/v1/admin/accounts", "/v1/admin/invites");
      await reload();
    } catch (e) {
      toast(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e), "bad");
    }
  };
  return (
    <Panel
      title={<span>{T.ac.invitedN(a.invited_total || a.invited.length)} <span className="hint font-normal">· {T.ac.inviteEarned(money(a.invite_earned_cny))}</span></span>}
      right={
        a.invited.length > 0 && (
          <Btn size="sm" variant="danger" onClick={reclaim}>
            {T.ac.abuse}
          </Btn>
        )
      }
      pad={false}
    >
      <DataTable
        rows={a.invited}
        rowKey={(i) => i.id}
        defaultSort="created_at"
        columns={[
          { key: "who", label: T.ac.invCols.who, sortable: false, render: (i) => <Who id={i.id} hint={i.hint} channel={i.channel} disabled={i.disabled} /> },
          { key: "created_at", label: T.ac.invCols.created, num: true, render: (i) => when(i.created_at) },
          { key: "last_seen_at", label: T.ac.invCols.last, num: true, render: (i) => <Ago ts={i.last_seen_at} /> },
          { key: "requests", label: T.ac.invCols.requests, num: true, render: (i) => fmt(i.requests) },
          { key: "spent_cny", label: T.ac.invCols.spent, num: true, render: (i) => money(i.spent_cny) },
          { key: "settled", label: T.ac.invCols.settled, render: (i) => (i.settled ? <Pill tone="ok">{T.ac.settled}</Pill> : <Pill>{T.ac.pending}</Pill>) },
          { key: "ip", label: T.ac.invCols.ip, sortable: false, render: (i) => <span className="inline-flex items-center gap-1"><IpChip ip={i.first_ip} />{i.first_ip === a.first_ip && <Pill tone="warn">= {T.ac.firstIp}</Pill>}</span> },
        ]}
      />
    </Panel>
  );
}

function SamplesTab({ id, total }: { id: string; total: number }) {
  const T = useT();
  const toast = useToast();
  const [rows, setRows] = useState<Sample[]>([]);
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const load = useCallback(
    async (before?: Sample) => {
      setLoading(true);
      try {
        const r = await get<{ samples: Sample[]; total: number }>(`/v1/admin/samples${qs({ account_id: id, limit: 30, before: before?.ts, before_id: before?.id })}`);
        setRows((xs) => (before ? [...xs, ...r.samples] : r.samples));
        setDone(r.samples.length < 30);
      } catch (e) {
        toast(e instanceof Error ? e.message : String(e), "bad");
      } finally {
        setLoading(false);
      }
    },
    [id, toast],
  );
  useEffect(() => {
    void load();
  }, [load]);
  const exportAll = () => download(`/v1/admin/samples/export?account_id=${encodeURIComponent(id)}`, `nanomuse-samples-${id.slice(0, 8)}.jsonl`).catch((e) => toast(String(e.message || e), "bad"));
  return (
    <Panel
      title={<span>{T.ac.tabs.samples} <span className="hint font-normal">{T.ac.ofTotal(rows.length, total)}</span></span>}
      sub={total > 0 ? T.ac.samplesHint : undefined}
      right={
        total > 0 && (
          <span className="flex items-center gap-3">
            {/* the same turns laid out one question at a time, pictures included; the drawer closes */}
            <a className="text-accent text-sm whitespace-nowrap" href={hashOf("turns", { account: id })}>
              {T.ac.samplesByQuestion} →
            </a>
            <Btn size="sm" onClick={exportAll}>
              {T.ac.samplesExport}
            </Btn>
          </span>
        )
      }
    >
      <div className="flex flex-col gap-2">
        {rows.map((s) => (
          <SampleCard key={s.id} s={s} />
        ))}
        {!rows.length && !loading && <div className="hint py-6 text-center">{T.ac.samplesNone}</div>}
        {!done && rows.length > 0 && (
          <Btn size="sm" className="self-start" onClick={() => load(rows[rows.length - 1])} disabled={loading}>
            {T.ac.loadMore}
          </Btn>
        )}
      </div>
    </Panel>
  );
}

function DemoTab({ d }: { d: AccountDetail }) {
  const T = useT();
  const zh = useZh();
  const now = useNow(10_000);
  const demo = d.demo;
  if (!demo || !demo.visitor) return <Panel><div className="hint py-6 text-center">{T.ac.demoNone}</div></Panel>;
  const v = demo.visitor;
  return (
    <>
      <Panel title={T.ac.tabs.demo}>
        <KV
          rows={[
            [T.de.cols.signins, fmt(v.signins)],
            [T.de.cols.sessions, fmt(v.sessions)],
            [T.de.cols.first, when(v.first_seen)],
            [T.de.cols.last, <Ago ts={v.last_seen} />],
            [T.de.cols.client, <span>{clientLine(v.last_ua)} · <IpChip ip={v.last_ip} /></span>],
          ]}
        />
      </Panel>
      <Panel title={T.ac.demoVisits(demo.visits_total)} pad={false}>
        <DataTable
          rows={demo.visits}
          rowKey={(x) => x.id}
          defaultSort="started"
          columns={[
            { key: "started", label: T.g.time, render: (x) => when(x.started) },
            { key: "length", label: T.de.length, num: true, value: (x) => (x.ended || now) - x.started, render: (x) => dur((x.ended || now) - x.started, zh) },
            { key: "reason", label: T.de.why, render: (x) => (x.ended ? nameOf(T.de.reason, x.reason) : <Pill tone="ok">{T.de.running}</Pill>) },
            { key: "byok", label: T.de.byok, render: (x) => (x.byok ? <Pill tone="violet">{T.de.byok}</Pill> : "·") },
            { key: "used", label: T.g.requests, num: true, value: (x) => x.requests || 0, render: (x) => T.de.used(x.requests || 0, x.tokens || 0) },
            { key: "ip", label: T.ac.addrCols.ip, render: (x) => <IpChip ip={x.ip} /> },
          ]}
        />
      </Panel>
    </>
  );
}
