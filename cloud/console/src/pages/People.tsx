/** Every account: searched and filtered client-side (the list is one answer), charted,
 *  sorted, exported, changed in batch; a row opens the account drawer. */

import { useMemo } from "react";
import { post } from "../lib/api";
import { clientLine } from "../lib/client";
import { dateOf, fmt, iso, matches, money, moneyN, nowS, siteDay, siteDayStart, terms } from "../lib/format";
import { invalidate, useData, useDebounced } from "../lib/hooks";
import { nameOf, useT } from "../lib/i18n";
import { placeOf, regionKey } from "../lib/places";
import { useRoute } from "../lib/router";
import type { Account, AccountsPage, Overview } from "../lib/types";
import { Bars, Ranks, platformColor } from "../ui/charts";
import { Bar, Btn, CsvButton, DataTable, Kpi, Panel, Pill, Search, useDialog, useToast, type Col } from "../ui/primitives";
import { Ago, PlatformPill, Who, usePlaces } from "../ui/who";
import { Loaded } from "./common";

const activityOf = (a: Account) => {
  const t = a.last_active_at || a.last_seen_at;
  if (!t) return "never";
  const d = nowS() - t;
  return d < 86400 ? "today" : d < 7 * 86400 ? "7d" : d < 30 * 86400 ? "30d" : "older";
};
const joinedOf = (a: Account) => {
  const d = nowS() - (a.created_at || 0);
  return d < 86400 ? "today" : d < 7 * 86400 ? "7d" : d < 30 * 86400 ? "30d" : "older";
};
const spendBucket = (a: Account) => {
  const c = Number(a.spent_cny || 0);
  return c <= 0 ? "0" : c < 1 ? "lt1" : c < 5 ? "1to5" : c < 10 ? "5to10" : "ge10";
};
const statusOk = (a: Account, s: string) =>
  !s ||
  (s === "member"
    ? a.member
    : s === "disabled"
      ? a.disabled
      : s === "locked"
        ? a.locked
        : s === "password"
          ? a.has_password
          : s === "nopassword"
            ? !a.has_password
            : s === "contributes"
              ? a.contribute
              : s === "exhausted"
                ? !a.member && a.left_cny !== null && a.left_cny !== undefined && Number(a.left_cny) <= 0
                : s === "online"
                  ? (a.devices || []).some((d) => d.online)
                  : s === "own"
                    ? (a.devices || []).some((d) => d.llm_provider)
                    : true);
const sourceOk = (a: Account, s: string) => !s || (s === "invited" ? !!a.invited_by : s === "organic" ? !a.invited_by : s === "inviter" ? Number(a.invites || 0) > 0 : true);

const SORTS: Record<string, (a: Account) => number | string> = {
  active: (a) => a.last_active_at || a.last_seen_at || 0,
  joined: (a) => a.created_at || 0,
  spent: (a) => Number(a.spent_cny || 0),
  today: (a) => Number(a.spent_today_cny || 0),
  requests: (a) => Number(a.requests || 0),
  left: (a) => (a.left_cny === null || a.left_cny === undefined ? -1 : Number(a.left_cny)),
  invites: (a) => Number(a.invites || 0),
  devices: (a) => (a.devices || []).length,
};

export function People() {
  const T = useT();
  const route = useRoute();
  const dialog = useDialog();
  const toast = useToast();
  usePlaces();
  const q = useData<AccountsPage>("/v1/admin/accounts", { poll: 120_000 });
  const ov = useData<Overview>("/v1/admin/overview?days=7", { maxAge: 300_000 });
  const p = route.params;
  const f = {
    q: p.get("q") || "",
    country: p.get("country") || "",
    province: p.get("province") || "",
    channel: p.get("channel") || "",
    status: p.get("status") || "",
    joined: p.get("joined") || "",
    activity: p.get("activity") || "",
    spend: p.get("spend") || "",
    source: p.get("source") || "",
    platform: p.get("platform") || "",
    version: p.get("version") || "",
    sort: p.get("sort") || "active",
    dir: p.get("dir") || "desc",
  };
  const qd = useDebounced(f.q, 150);
  const set = (patch: Record<string, string | null>) => route.set(patch, true);
  const toggle = (k: string, v: string) => set({ [k]: f[k as keyof typeof f] === v ? null : v });

  const list = q.data?.accounts || [];
  const haystack = (a: Account) =>
    [a.identifier, a.hint, a.id, a.first_ip, a.last_ip, a.last_version, a.last_platform, nameOf(T.platforms, a.last_platform), clientLine(a.last_ua), ...(a.devices || []).map((d) => `${d.name || ""} ${d.kind || ""} ${d.os || ""} ${d.llm_provider || ""} ${d.llm_model || ""}`), placeOf(a.last_ip)?.text || "", a.invited_by || "", a.invite_code]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
  const base = useMemo(() => {
    const ts = terms(qd);
    return list.filter(
      (a) =>
        (!ts.length || matches(haystack(a), ts)) &&
        (!f.channel || (f.channel === "phone" ? a.channel !== "email" : a.channel === "email")) &&
        statusOk(a, f.status) &&
        (!f.activity || activityOf(a) === f.activity) &&
        (!f.spend || spendBucket(a) === f.spend) &&
        (!f.platform || (a.last_platform || "") === f.platform) &&
        (!f.joined || joinedOf(a) === f.joined) &&
        sourceOk(a, f.source) &&
        (!f.version || (a.last_version || "") === f.version),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list, qd, f.channel, f.status, f.activity, f.spend, f.platform, f.joined, f.source, f.version, T]);
  const shown = useMemo(() => {
    const rows = f.country || f.province ? base.filter((a) => { const pl = placeOf(a.last_ip); return (!f.country || regionKey(pl) === f.country) && (!f.province || (pl?.province || "") === f.province); }) : [...base];
    const key = SORTS[f.sort] || SORTS.active;
    const sign = f.dir === "asc" ? 1 : -1;
    rows.sort((a, b) => {
      const x = key(a),
        y = key(b);
      return (typeof x === "string" ? x.localeCompare(String(y)) : x - Number(y)) * sign || (b.created_at || 0) - (a.created_at || 0);
    });
    return rows;
  }, [base, f.country, f.province, f.sort, f.dir]);

  const count = <K,>(xs: Account[], keyOf: (a: Account) => K) => {
    const m = new Map<K, number>();
    for (const x of xs) m.set(keyOf(x), (m.get(keyOf(x)) || 0) + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  };
  const countries = count(base, (a) => regionKey(placeOf(a.last_ip)));
  const provinces = f.country ? count(base.filter((a) => regionKey(placeOf(a.last_ip)) === f.country), (a) => placeOf(a.last_ip)?.province || "").filter(([k]) => k) : [];
  const versions = count(base.filter((a) => a.last_version), (a) => a.last_version).sort((x, y) => y[0].localeCompare(x[0], undefined, { numeric: true }));
  const activeFilters = ["country", "province", "channel", "status", "joined", "activity", "spend", "source", "platform", "version"].filter((k) => f[k as keyof typeof f]).length + (f.q ? 1 : 0);

  const batch = async (rows: Account[], all: boolean) => {
    const limited = rows.filter((a) => !a.member);
    const r = await dialog({
      title: T.pe.batch,
      body: T.pe.batchHint,
      fields: [
        { id: "mode", label: T.pe.sortBy, type: "select", value: "delta_cny", options: Object.entries(T.pe.batchMode).map(([id, label]) => ({ id, label })) },
        { id: "cny", label: T.se.amount, type: "number", step: "0.01" },
        { id: "note", label: T.g.note, type: "text" },
      ],
    });
    if (!r) return;
    const cny = Number(r.cny);
    if (!Number.isFinite(cny)) return;
    const what = `${T.pe.batchMode[String(r.mode)]} ${money(cny)}`;
    const ok = await dialog({ title: T.pe.batch, body: T.pe.batchConfirm(all ? T.pe.batchAll : T.pe.batchShown(limited.length), what), danger: true });
    if (!ok) return;
    try {
      const out = await post<{ changed?: number; updated?: number }>("/v1/admin/pool/batch", { ...(all ? { all: true } : { account_ids: limited.map((a) => a.id) }), [String(r.mode)]: cny, note: String(r.note || "") });
      toast(T.pe.batchDone(out.changed ?? out.updated ?? limited.length), "ok");
      invalidate("/v1/admin/accounts", "/v1/admin/overview");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "bad");
    }
  };

  const cols: Col<Account>[] = [
    {
      key: "who",
      label: T.pe.who,
      sortable: false,
      render: (a) => (
        <Who
          id={a.id}
          hint={a.hint}
          identifier={a.identifier}
          channel={a.channel}
          disabled={a.disabled}
          member={a.member}
          tags={
            <>
              {a.member && <Pill tone="violet">{T.pe.tags.member}</Pill>}
              {a.disabled && <Pill tone="bad">{T.pe.tags.disabled}</Pill>}
              {a.locked && <Pill tone="warn">{T.pe.tags.locked}</Pill>}
              {a.review && <Pill tone="cyan">{T.pe.tags.review}</Pill>}
              {a.contribute && <Pill tone="ok">{T.pe.tags.contribute}</Pill>}
              {(a.devices || []).some((d) => d.llm_provider) && <Pill tone="accent">{T.pe.tags.own}</Pill>}
            </>
          }
          sub={placeOf(a.last_ip)?.text ? <span className="truncate">{placeOf(a.last_ip)!.local ? T.g.local : [placeOf(a.last_ip)!.country, placeOf(a.last_ip)!.province].filter(Boolean).join(" ")}</span> : null}
        />
      ),
    },
    { key: "created_at", label: T.pe.created, num: true, render: (a) => <span title={dateOf(a.created_at)}><Ago ts={a.created_at} /></span> },
    { key: "last", label: T.pe.lastSeen, num: true, value: (a) => a.last_active_at || a.last_seen_at || 0, render: (a) => <Ago ts={a.last_active_at || a.last_seen_at} /> },
    { key: "client", label: T.pe.client, sortable: false, render: (a) => <PlatformPill platform={a.last_platform} version={a.last_version} /> },
    {
      key: "pool",
      label: T.pe.pool,
      value: (a) => (a.member ? 1e9 : Number(a.left_cny ?? 0)),
      render: (a) =>
        a.member ? (
          <span className="hint">{T.g.unlimited}</span>
        ) : (
          <div className="min-w-[110px]">
            <div className="text-[12px]">{T.pe.poolLine(money(a.left_cny), money(a.grant_cny))}</div>
            <Bar value={Math.max(0, Number(a.grant_cny || 0) - Number(a.left_cny || 0))} max={Number(a.grant_cny || 0) || 1} tone={Number(a.left_cny || 0) <= 0 ? "bad" : Number(a.left_cny || 0) < Number(a.grant_cny || 0) * 0.2 ? "warn" : "accent"} className="mt-1" />
          </div>
        ),
    },
    { key: "spent_cny", label: T.pe.spent, num: true, render: (a) => <span title={`${T.g.today} ${money(a.spent_today_cny)}`}>{money(a.spent_cny)}</span> },
    { key: "requests", label: T.pe.requests, num: true, render: (a) => fmt(a.requests) },
    { key: "devices", label: T.pe.devices, num: true, value: (a) => (a.devices || []).length, render: (a) => <span>{(a.devices || []).length}{(a.devices || []).some((d) => d.online) && <span className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-ok align-middle" />}</span> },
    { key: "invites", label: T.in.title, num: true, hideSm: true, render: (a) => (a.invites ? fmt(a.invites) : "·") },
  ];
  const csvCols: Col<Account>[] = [
    { key: "identifier", label: "identifier", csv: (a) => a.identifier || "" },
    { key: "hint", label: "hint", csv: (a) => a.hint },
    { key: "id", label: "id", csv: (a) => a.id },
    { key: "channel", label: "channel", csv: (a) => a.channel },
    { key: "joined", label: "joined", csv: (a) => iso(a.created_at) },
    { key: "region", label: "region", csv: (a) => placeOf(a.last_ip)?.text || "" },
    { key: "spent_cny", label: "spent_cny", csv: (a) => moneyN(a.spent_cny) },
    { key: "spent_today_cny", label: "spent_today_cny", csv: (a) => moneyN(a.spent_today_cny) },
    { key: "left_cny", label: "left_cny", csv: (a) => (a.left_cny === null || a.left_cny === undefined ? "" : moneyN(a.left_cny)) },
    { key: "tokens", label: "tokens", csv: (a) => a.used || 0 },
    { key: "requests", label: "requests", csv: (a) => a.requests || 0 },
    { key: "last_active", label: "last_active", csv: (a) => iso(a.last_active_at) },
    { key: "member", label: "member", csv: (a) => (a.member ? 1 : 0) },
    { key: "disabled", label: "disabled", csv: (a) => (a.disabled ? 1 : 0) },
    { key: "password", label: "password", csv: (a) => (a.has_password ? 1 : 0) },
    { key: "client", label: "client", csv: (a) => a.last_platform || "" },
    { key: "version", label: "version", csv: (a) => a.last_version || "" },
    { key: "devices", label: "devices", csv: (a) => (a.devices || []).length },
    { key: "invited_by", label: "invited_by", csv: (a) => a.invited_by || "" },
    { key: "invites", label: "invites", csv: (a) => a.invites || 0 },
  ];

  const Select = ({ label, value, options, onChange }: { label: string; value: string; options: [string, string, number?][]; onChange: (v: string) => void }) => (
    <label className="inline-flex items-center gap-1 text-[12px] text-ink-3">
      {label}
      <select className="inp py-1 text-[12.5px] text-ink" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{T.pe.any}</option>
        {options.map(([k, l, n]) => (
          <option key={k} value={k}>
            {l}
            {n !== undefined ? ` (${n})` : ""}
          </option>
        ))}
      </select>
    </label>
  );

  // sign-ups per day for the shown set, last 30 days — site-local days, so a bar is the
  // day the site's calendar says, the same day the Usage page and the relay count
  const offsetH = Number(ov.data?.settings.day_offset_h || 0);
  const signups = useMemo(() => {
    const t = nowS();
    const start = siteDayStart(t, offsetH) - 29 * 86400;
    const per = new Array(30).fill(0);
    for (const a of shown) if (a.created_at >= start) per[Math.min(29, Math.floor((a.created_at - start) / 86400))]++;
    return { per, start };
  }, [shown, offsetH]);

  return (
    <Loaded q={q}>
      {() => (
        <>
          <Panel pad={false}>
            <div className="flex flex-wrap items-center gap-2 px-4 pt-3">
              <Search value={f.q} onChange={(v) => set({ q: v })} placeholder={T.pe.search} className="w-full max-w-[420px]" />
              <span className="hint">{T.pe.shown(shown.length, list.length)}</span>
              <div className="ml-auto flex flex-wrap gap-2">
                <CsvButton name="nanomuse-accounts" columns={csvCols} rows={shown} label={T.pe.export} />
                <Btn size="sm" onClick={() => batch(shown, false)} disabled={!shown.some((a) => !a.member)}>
                  {T.pe.batch} ({shown.filter((a) => !a.member).length})
                </Btn>
                <Btn size="sm" onClick={() => batch([], true)}>
                  {T.pe.batch} · {T.pe.batchAll}
                </Btn>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
              <Select label={T.pe.fRegion} value={f.country} options={countries.map(([k, n]) => [k, k === "本地网络" ? T.g.local : k || T.g.unknown, n])} onChange={(v) => set({ country: v, province: null })} />
              {f.country && provinces.length > 0 && <Select label={T.pe.fProvince} value={f.province} options={provinces.map(([k, n]) => [k, k, n])} onChange={(v) => set({ province: v })} />}
              <Select label={T.pe.fChannel} value={f.channel} options={[["phone", T.channels.phone], ["email", T.channels.email]]} onChange={(v) => set({ channel: v })} />
              <Select label={T.pe.fStatus} value={f.status} options={Object.entries(T.pe.status)} onChange={(v) => set({ status: v })} />
              <Select label={T.pe.fJoined} value={f.joined} options={Object.entries(T.pe.joined)} onChange={(v) => set({ joined: v })} />
              <Select label={T.pe.fActivity} value={f.activity} options={Object.entries(T.pe.activity)} onChange={(v) => set({ activity: v })} />
              <Select label={T.pe.fSpend} value={f.spend} options={Object.entries(T.pe.spend)} onChange={(v) => set({ spend: v })} />
              <Select label={T.pe.fSource} value={f.source} options={Object.entries(T.pe.source)} onChange={(v) => set({ source: v })} />
              <Select label={T.pe.fClient} value={f.platform} options={Object.entries(T.platforms)} onChange={(v) => set({ platform: v })} />
              {(versions.length > 0 || f.version) && <Select label={T.pe.fVersion} value={f.version} options={versions.map(([k, n]) => [k, `v${k}`, n])} onChange={(v) => set({ version: v })} />}
              <Select label={T.pe.sortBy} value={f.sort} options={Object.entries(T.pe.sorts)} onChange={(v) => set({ sort: v || null })} />
              {activeFilters > 0 && (
                <button type="button" className="chip" onClick={() => route.set(Object.fromEntries(["q", "country", "province", "channel", "status", "joined", "activity", "spend", "source", "platform", "version"].map((k) => [k, null])), true)}>
                  {T.pe.fClear} ({activeFilters})
                </button>
              )}
            </div>
          </Panel>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-4">
            <Panel title={T.pe.chartCreated} sub={`30 ${T.top.days(30).replace(/^\d+\s?/, "")}`} className="lg:col-span-2">
              <Bars series={[{ name: T.pe.created, values: signups.per, color: "var(--c1)" }]} labels={signups.per.map((_, i) => siteDay(signups.start + i * 86400, offsetH).slice(5))} height={120} />
            </Panel>
            <Panel title={T.pe.chartActivity}>
              <Ranks rows={["today", "7d", "30d", "older", "never"].map((k, i) => ({ name: T.pe.activity[k], value: shown.filter((a) => activityOf(a) === k).length, color: ["var(--ok)", "var(--c1)", "var(--c5)", "var(--ink-3)", "var(--warn)"][i], onClick: () => toggle("activity", k) }))} showShare />
            </Panel>
            <Panel title={T.pe.chartPlatforms}>
              <Ranks rows={count(shown, (a) => a.last_platform || "").slice(0, 7).map(([k, n]) => ({ name: k ? nameOf(T.platforms, k) : T.g.unknown, value: n, color: platformColor(k), onClick: k ? () => toggle("platform", k) : undefined }))} showShare />
            </Panel>
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Kpi label={T.pe.spent} value={money(shown.reduce((t, a) => t + Number(a.spent_cny || 0), 0))} sub={`${T.g.today} ${money(shown.reduce((t, a) => t + Number(a.spent_today_cny || 0), 0))}`} />
            <Kpi label={T.pe.status.member} value={fmt(shown.filter((a) => a.member).length)} onClick={() => toggle("status", "member")} />
            <Kpi label={T.pe.status.exhausted} value={fmt(shown.filter((a) => statusOk(a, "exhausted")).length)} onClick={() => toggle("status", "exhausted")} tone="warn" />
            <Kpi label={T.pe.status.disabled} value={fmt(shown.filter((a) => a.disabled).length)} onClick={() => toggle("status", "disabled")} tone="bad" />
          </div>
          <Panel pad={false}>
            <DataTable rows={shown} rowKey={(a) => a.id} columns={cols} onRow={(a) => route.set({ acct: a.id })} limit={100} empty={T.pe.noMatch} selectedKey={p.get("acct") || undefined} />
          </Panel>
          <div className="hint">{T.pe.rowHint}</div>
        </>
      )}
    </Loaded>
  );
}
