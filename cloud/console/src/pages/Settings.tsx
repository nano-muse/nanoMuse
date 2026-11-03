/** What the operator can change while the relay runs (allowance, invite bonus, sign-ups),
 *  the broad pool actions, the nudges policy, and the environment read-only. */

import { useEffect, useRef, useState } from "react";
import { post, put } from "../lib/api";
import { fmt, money, usd, when } from "../lib/format";
import { invalidate, useData } from "../lib/hooks";
import { sameDraft } from "../lib/drafts";
import { nameOf, useT } from "../lib/i18n";
import type { Nudges, NudgesPolicy, Overview, RuntimeSettings, Settings } from "../lib/types";
import { Btn, Field, Grid, KV, Note, Panel, Pill, Toggle, useDialog, useToast } from "../ui/primitives";
import { Loaded } from "./common";

export function SettingsPage() {
  const rt = useData<RuntimeSettings>("/v1/admin/settings", { poll: 120_000 });
  const ov = useData<Overview>("/v1/admin/overview?days=7", { maxAge: 120_000 });
  const nu = useData<Nudges>("/v1/admin/nudges", { poll: 300_000 });
  return (
    <>
      <Loaded q={rt}>{(r) => <Runtime r={r} reload={() => void rt.reload()} />}</Loaded>
      <Loaded q={nu}>{(n) => <NudgesEditor n={n} reload={() => void nu.reload()} />}</Loaded>
      <Loaded q={ov}>{(o) => <Environment s={o.settings} />}</Loaded>
    </>
  );
}

function Runtime({ r, reload }: { r: RuntimeSettings; reload: () => void }) {
  const T = useT();
  const dialog = useDialog();
  const toast = useToast();
  const [allowance, setAllowance] = useState(String(r.values.allowance_cny));
  const [bonus, setBonus] = useState(String(r.values.invite_bonus_cny));
  const [busy, setBusy] = useState("");
  // a poll that changed nothing (a fresh object, same numbers) must not reseed
  // what the operator is typing; a value that moved on the server still does
  const seeded = useRef([String(r.values.allowance_cny), String(r.values.invite_bonus_cny)]);
  useEffect(() => {
    const incoming = [String(r.values.allowance_cny), String(r.values.invite_bonus_cny)];
    if (sameDraft(seeded.current, incoming)) return;
    seeded.current = incoming;
    setAllowance(incoming[0]);
    setBonus(incoming[1]);
  }, [r]);
  const act = async (key: string, fn: () => Promise<string | void>) => {
    setBusy(key);
    try {
      const msg = await fn();
      invalidate("/v1/admin/settings", "/v1/admin/overview", "/v1/admin/accounts");
      reload();
      toast(msg || T.se.saved, "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "bad");
    } finally {
      setBusy("");
    }
  };
  const save = (body: Record<string, unknown>) => act("save", () => post("/v1/admin/settings", body).then(() => undefined));
  const creditAll = async () => {
    const r1 = await dialog({ title: T.se.creditAll, fields: [{ id: "cny", label: T.se.amount, type: "number", step: "0.01" }, { id: "note", label: T.g.note, type: "text" }] });
    if (!r1) return;
    const cny = Number(r1.cny);
    if (!Number.isFinite(cny) || cny === 0) return;
    if (!(await dialog({ title: T.se.creditAll, body: T.se.creditAllConfirm(money(cny)), danger: true }))) return;
    await act("credit", async () => T.se.credited((await post<{ accounts: number }>("/v1/admin/credit-all", { cny, note: String(r1.note || "") })).accounts));
  };
  const setAll = async () => {
    const r1 = await dialog({
      title: T.se.setAll,
      fields: [
        { id: "mode", label: T.pe.sortBy, type: "select", value: "left_cny", options: Object.entries(T.pe.batchMode).map(([id, label]) => ({ id, label })) },
        { id: "cny", label: T.se.amount, type: "number", step: "0.01" },
        { id: "note", label: T.g.note, type: "text" },
      ],
    });
    if (!r1) return;
    const cny = Number(r1.cny);
    if (!Number.isFinite(cny)) return;
    const what = `${T.pe.batchMode[String(r1.mode)]} ${money(cny)}`;
    if (!(await dialog({ title: T.se.setAll, body: T.se.setAllConfirm(what), danger: true }))) return;
    await act("setall", async () => T.pe.batchDone((await post<{ accounts: number }>("/v1/admin/pool/batch", { all: true, [String(r1.mode)]: cny, note: String(r1.note || "") })).accounts));
  };
  const applyAllowance = async () => {
    if (!(await dialog({ title: T.se.apply, body: T.se.applySub(r.below_allowance) }))) return;
    await act("apply", async () => T.se.applied((await post<{ accounts: number }>("/v1/admin/allowance/apply")).accounts));
  };
  const rowProps = (k: keyof RuntimeSettings["values"]) => ({ overridden: r.overridden[k], env: String(r.env[k]), onClear: () => save({ [k]: null }), busy: !!busy });
  return (
    <Panel title={T.se.runtime} sub={T.se.runtimeNote}>
      <SettingRow label={T.se.allowance} {...rowProps("allowance_cny")}>
        <div className="flex gap-2">
          <input className="inp w-32" type="number" min={0} step="0.01" value={allowance} onChange={(e) => setAllowance(e.target.value)} />
          <Btn variant="primary" size="sm" onClick={() => save({ allowance_cny: Number(allowance) })} disabled={!!busy || Number(allowance) === r.values.allowance_cny}>
            {T.g.save}
          </Btn>
          {r.below_allowance > 0 && (
            <Btn size="sm" onClick={applyAllowance} disabled={!!busy}>
              {T.se.apply} ({fmt(r.below_allowance)})
            </Btn>
          )}
        </div>
      </SettingRow>
      <SettingRow label={T.se.inviteBonus} {...rowProps("invite_bonus_cny")}>
        <div className="flex gap-2">
          <input className="inp w-32" type="number" min={0} step="0.01" value={bonus} onChange={(e) => setBonus(e.target.value)} />
          <Btn variant="primary" size="sm" onClick={() => save({ invite_bonus_cny: Number(bonus) })} disabled={!!busy || Number(bonus) === r.values.invite_bonus_cny}>
            {T.g.save}
          </Btn>
        </div>
      </SettingRow>
      <SettingRow label={T.se.signupOpen} {...rowProps("signup_open")}>
        <Toggle on={r.values.signup_open} onChange={(v) => save({ signup_open: v })} disabled={!!busy} label={r.values.signup_open ? T.g.on : T.g.off} />
      </SettingRow>
      <div className="mt-3 flex flex-wrap gap-2">
        <Btn onClick={creditAll} disabled={!!busy}>
          {T.se.creditAll}
        </Btn>
        <Btn onClick={setAll} disabled={!!busy}>
          {T.se.setAll}
        </Btn>
      </div>
    </Panel>
  );
}

function SettingRow({ label, overridden, env, onClear, busy, children }: { label: string; overridden: boolean; env: string; onClear: () => void; busy: boolean; children: React.ReactNode }) {
  const T = useT();
  return (
    <div className="flex flex-wrap items-end gap-2 border-b border-line py-3 last:border-0">
      <Field
        label={
          <span className="inline-flex items-center gap-2">
            {label}
            {overridden && <Pill tone="accent">{T.se.overridden}</Pill>}
          </span>
        }
        hint={T.se.env(env)}
        className="min-w-[220px]"
      >
        {children}
      </Field>
      {overridden && (
        <Btn size="sm" onClick={onClear} disabled={busy}>
          {T.se.clear}
        </Btn>
      )}
    </div>
  );
}

function NudgesEditor({ n, reload }: { n: Nudges; reload: () => void }) {
  const T = useT();
  const toast = useToast();
  const dialog = useDialog();
  const [p, setP] = useState<NudgesPolicy>(n.nudges);
  const [tasks, setTasks] = useState(n.nudges.star.moments.tasks.join(", "));
  const [daysUsed, setDaysUsed] = useState(n.nudges.star.moments.days_used.join(", "));
  const [busy, setBusy] = useState(false);
  const seeded = useRef(n.nudges);
  useEffect(() => {
    if (sameDraft(seeded.current, n.nudges)) return;  // the 5-minute poll, unchanged
    seeded.current = n.nudges;
    setP(n.nudges);
    setTasks(n.nudges.star.moments.tasks.join(", "));
    setDaysUsed(n.nudges.star.moments.days_used.join(", "));
  }, [n]);
  const star = (patch: Partial<NudgesPolicy["star"]>) => setP({ ...p, star: { ...p.star, ...patch } });
  const moment = (patch: Partial<NudgesPolicy["star"]["moments"]>) => star({ moments: { ...p.star.moments, ...patch } });
  const list = (s: string) => s.split(/[\s,，]+/).map(Number).filter((x) => Number.isFinite(x) && x > 0);
  const send = async (body: unknown, msg: string) => {
    setBusy(true);
    try {
      await put("/v1/admin/nudges", body);
      invalidate("/v1/admin/nudges");
      reload();
      toast(msg, "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "bad");
    } finally {
      setBusy(false);
    }
  };
  const save = () => send({ version: p.version, star: { ...p.star, moments: { ...p.star.moments, tasks: list(tasks), days_used: list(daysUsed) } } }, T.se.saved);
  const reset = async () => {
    if (!(await dialog({ title: T.se.nudges, body: T.g.reset, danger: true }))) return;
    await send({ reset: true }, T.g.done);
  };
  return (
    <Panel
      title={T.se.nudges}
      sub={
        <>
          {T.se.nudgesNote} · v{n.nudges.version} · {n.stored && n.updated_at ? T.se.nuStored(when(n.updated_at)) : T.se.nuDefaults}
        </>
      }
      right={
        <>
          <Btn size="sm" onClick={reset} disabled={busy || !n.stored}>
            {T.g.reset}
          </Btn>
          <Btn size="sm" variant="primary" onClick={save} disabled={busy}>
            {T.g.save}
          </Btn>
        </>
      }
    >
      <Grid cols={2}>
        <div className="flex flex-col gap-3">
          <Toggle on={p.star.enabled} onChange={(v) => star({ enabled: v })} label={T.se.nuEnabled} />
          <Field label={T.se.nuUrl}>
            <input className="inp" value={p.star.url} onChange={(e) => star({ url: e.target.value })} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={T.se.nuCooldown}>
              <input className="inp" type="number" min={0} value={p.star.cooldown_days} onChange={(e) => star({ cooldown_days: Number(e.target.value) })} />
            </Field>
            <Field label={T.se.nuMaxAsks}>
              <input className="inp" type="number" min={0} value={p.star.max_asks} onChange={(e) => star({ max_asks: Number(e.target.value) })} />
            </Field>
          </div>
          <Field label={T.se.nuText}>
            <input className="inp" value={p.star.text} onChange={(e) => star({ text: e.target.value })} />
          </Field>
          <Field label={T.se.nuTextZh}>
            <input className="inp" value={p.star.text_zh} onChange={(e) => star({ text_zh: e.target.value })} />
          </Field>
        </div>
        <div className="flex flex-col gap-3">
          <div className="hint">{T.se.nuMoments}</div>
          <Toggle on={p.star.moments.signed_in} onChange={(v) => moment({ signed_in: v })} label={T.se.nuSignedIn} />
          <Toggle on={p.star.moments.new_look} onChange={(v) => moment({ new_look: v })} label={T.se.nuNewLook} />
          <Toggle on={p.star.moments.exhausted} onChange={(v) => moment({ exhausted: v })} label={T.se.nuExhausted} />
          <Toggle on={p.star.moments.goal_done} onChange={(v) => moment({ goal_done: v })} label={T.se.nuGoalDone} />
          <Field label={T.se.nuTasks}>
            <input className="inp" value={tasks} onChange={(e) => setTasks(e.target.value)} />
          </Field>
          <Field label={T.se.nuDaysUsed}>
            <input className="inp" value={daysUsed} onChange={(e) => setDaysUsed(e.target.value)} />
          </Field>
        </div>
      </Grid>
    </Panel>
  );
}

function Environment({ s }: { s: Settings }) {
  const T = useT();
  const yesNo = (b: boolean) => (b ? T.g.on : T.g.off);
  const rows: [string, React.ReactNode][] = [
    [T.se.rows.allowance_cny, `${money(s.allowance_cny)} (${usd(s.allowance_cny, s.usd_cny)})`],
    [T.se.rows.invitee_bonus_cny, money(s.invitee_bonus_cny)],
    [T.se.rows.contribute_bonus_cny, money(s.contribute_bonus_cny)],
    [T.se.rows.usd_cny, String(s.usd_cny)],
    [T.se.rows.day_offset_h, String(s.day_offset_h)],
    [T.se.rows.per_minute_requests, fmt(s.per_minute_requests)],
    [T.se.rows.password_min_len, String(s.password_min_len)],
    [T.se.rows.signup_per_domain_day, fmt(s.signup_per_domain_day)],
    [T.se.rows.sender, s.sender || "·"],
    [T.se.rows.improve_default, yesNo(s.improve_default)],
    [T.se.rows.models, <span key="m" className="flex flex-wrap gap-1">{s.models.map((m) => <code key={m}>{m}<span className="hint"> {nameOf(T.kinds, s.model_kinds[m] || "chat")}</span></code>)}</span>],
    [T.se.rows.allowed_identifiers, s.allowed_identifiers.length ? `${s.allowed_identifiers.length}` : T.g.empty],
    [T.se.rows.signup_domain_allow, s.signup_domain_allow.length ? s.signup_domain_allow.join(", ") : T.g.all],
    [T.se.rows.repo_url, <a key="r" href={s.repo_url} target="_blank" rel="noreferrer">{s.repo_url}</a>],
    [T.se.rows.invite_url, s.invite_url],
    [T.se.rows.privacy_url, s.privacy_url],
    [T.se.rows.own_key_docs, s.own_key_docs],
  ];
  return (
    <Panel title={T.se.config} sub={T.se.version(s.version)}>
      {s.paused.length > 0 && <Note tone="warn" className="mb-3">{T.ov.paused(s.paused.map((k) => nameOf(T.ct.names, k)).join(", "))}</Note>}
      <KV rows={rows} />
    </Panel>
  );
}
