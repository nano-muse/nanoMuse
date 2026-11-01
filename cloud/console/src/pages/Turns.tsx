/** The record question by question: one card per question a person asked (or a routine
 *  ran), with every model call it took laid out as steps — what the model said or which
 *  tools it called, what came back (tool results, the hands' screenshots, a message the
 *  person added), and the reply the person saw. Pictures and clips are shown where they
 *  were sent. The figures at the top count questions beside calls. */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { PageProps } from "../App";
import { get, qs } from "../lib/api";
import { compact, dur, fmt, nowS, when } from "../lib/format";
import { useData, useDebounced } from "../lib/hooks";
import { nameOf, useT, useZh } from "../lib/i18n";
import { useRoute } from "../lib/router";
import { LatestRequest } from "../lib/latest-request";
import type { RecordView, TurnFull, TurnGroup, TurnGroups, TurnMessage, TurnStep } from "../lib/types";
import { Ranks, modelColor } from "../ui/charts";
import { isBlobRef, partsOf, toolArgs } from "../lib/turns";
import { BlobView } from "../ui/blob";
import { Btn, Chips, Drawer, Empty, Failed, Kpi, Kpis, Loading, Note, Panel, Pill, Search, cx } from "../ui/primitives";
import { PlatformPill, Who } from "../ui/who";
import { Loaded } from "./common";

const PAGE = 20;
const CLAMP = 600;

// -- what a message holds -------------------------------------------------------------------

/** Text that folds past CLAMP characters, kept as written (whitespace and all). */
function Clamped({ text, className, limit = CLAMP }: { text: string; className?: string; limit?: number }) {
  const T = useT();
  const [open, setOpen] = useState(false);
  const long = text.length > limit;
  return (
    <div className={className}>
      <pre className="font-sans text-[13px] leading-relaxed whitespace-pre-wrap break-words">{open || !long ? text : text.slice(0, limit) + "…"}</pre>
      {long && (
        <button type="button" className="mt-1 text-[12px] text-accent" onClick={() => setOpen((v) => !v)}>
          {open ? T.tu.fold : `${T.tu.expand} (${compact(text.length)})`}
        </button>
      )}
    </div>
  );
}

function Files({ files, size }: { files: string[]; size?: number }) {
  if (!files.length) return null;
  return (
    <div className="mt-1.5 flex flex-wrap gap-2">
      {files.map((f, i) => (isBlobRef(f) ? <BlobView key={`${f}-${i}`} refer={f} size={size} /> : <a key={`${f}-${i}`} href={f} target="_blank" rel="noreferrer" className="inline-block overflow-hidden rounded-md border border-line"><img src={f} alt="" style={{ maxHeight: size || 160 }} className="block" loading="lazy" /></a>))}
    </div>
  );
}

/** One message as the record keeps it: the person's words and pictures, the model's words,
 *  its reasoning folded, the tools it called with their arguments, a tool's result. */
export function MessageView({ m, label, tone, size }: { m: TurnMessage; label?: ReactNode; tone?: "person" | "model" | "final" | "tool" | "system"; size?: number }) {
  const T = useT();
  const { text, files } = partsOf(m.content);
  const calls = m.tool_calls || [];
  const kind = tone || (m.role === "user" ? "person" : m.role === "assistant" ? "model" : m.role === "tool" ? "tool" : "system");
  return (
    <div className={cx("rounded-lg border px-3 py-2", kind === "person" ? "border-accent/30 bg-accent-soft/40" : kind === "final" ? "border-ok/30 bg-ok-soft/30" : kind === "tool" ? "border-line bg-panel-2" : kind === "system" ? "border-dashed border-line" : "border-line bg-panel")}>
      {label !== undefined && <div className="mb-1 flex flex-wrap items-center gap-1.5 text-[11.5px] text-ink-3">{label}</div>}
      {m.reasoning_content && (
        <details className="mb-1.5">
          <summary className="cursor-pointer text-[12px] text-ink-3">{T.tu.thought}</summary>
          <Clamped text={m.reasoning_content} className="mt-1 text-ink-2" />
        </details>
      )}
      {text && <Clamped text={text} />}
      {m.truncated && <div className="hint mt-1">{T.tu.truncated}</div>}
      <Files files={files} size={size} />
      {calls.length > 0 && (
        <div className={cx("flex flex-col gap-1.5", (text || files.length > 0) && "mt-2")}>
          {calls.map((c, i) => {
            const args = toolArgs(c.function?.arguments);
            return (
              <details key={c.id || i} className="rounded-md border border-violet/30 bg-violet-soft/40 px-2.5 py-1.5">
                <summary className="cursor-pointer text-[12.5px]">
                  <span className="font-medium text-violet">{c.function?.name || "?"}</span>
                  {args && <span className="ml-2 text-ink-3">{args.replace(/\s+/g, " ").slice(0, 120)}</span>}
                </summary>
                {args && <pre className="mono mt-1.5 max-h-80 overflow-auto text-[12px] whitespace-pre-wrap break-words">{args}</pre>}
              </details>
            );
          })}
        </div>
      )}
      {!text && !files.length && !calls.length && !m.reasoning_content && <span className="hint">–</span>}
    </div>
  );
}

// -- a question laid out -----------------------------------------------------------------------

/** A user message that arrived between two calls is the hands' screenshot when it carries a
 *  picture and little else; otherwise the person added something. */
const isScreenshot = (m: TurnMessage): boolean => {
  const { text, files } = partsOf(m.content);
  return files.length > 0 && (!text || text.length < 80);
};

function StepView({ step, i, n, onWhole }: { step: TurnStep; i: number; n: number; onWhole: (id: string) => void }) {
  const T = useT();
  const c = step.call;
  const tools = step.reply.tool_calls?.length || 0;
  const bad = c.status && c.status !== "ok" && c.status !== "200";
  const final = i === n && !tools;
  return (
    <li className="relative pl-7">
      <span className={cx("absolute top-1.5 left-0 grid h-5 w-5 place-items-center rounded-full border text-[10.5px] font-semibold", bad ? "border-bad bg-bad-soft text-bad" : tools ? "border-violet bg-violet-soft text-violet" : "border-accent bg-accent-soft text-accent")}>{i}</span>
      <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px] text-ink-3">
        <span className="font-medium text-ink-2">{T.tu.step(i, n)}</span>
        <code title={c.model}>{c.model}</code>
        <span>{when(c.ts)}</span>
        <span>{T.tu.tokens(compact(c.prompt_tokens), compact(c.completion_tokens))}</span>
        <span>{T.tu.saw(step.messages)}</span>
        {tools > 0 && <Pill tone="violet">{T.tu.calledTools(tools)}</Pill>}
        {bad && <Pill tone="bad">{c.status}</Pill>}
        {c.source === "own" && <Pill>{nameOf(T.da.sources, "own")}</Pill>}
        <button type="button" className="text-accent" onClick={() => onWhole(c.id)}>
          {T.tu.whole}
        </button>
      </div>
      <MessageView m={step.reply} tone={final ? "final" : "model"} label={final ? <span className="font-medium text-ok">{T.tu.reply}</span> : undefined} />
      {final && !partsOf(step.reply.content).text && !step.reply.tool_calls?.length && <div className="hint mt-1">{T.tu.noReply}</div>}
      {step.then.length > 0 && (
        <div className="mt-1.5 ml-3 flex flex-col gap-1.5 border-l-2 border-line pl-3">
          {step.then.map((m, j) => (
            <MessageView key={j} m={m} label={m.role === "tool" ? <><span className="font-medium">{T.tu.result}</span>{m.name && <code>{m.name}</code>}{m.tool_call_id && <code className="opacity-60">{m.tool_call_id}</code>}</> : m.role === "user" ? <span className="font-medium">{isScreenshot(m) ? T.tu.screenshot : T.tu.added}</span> : <span>{nameOf(T.tu.roles, m.role)}</span>} tone={m.role === "user" ? "person" : m.role === "tool" ? "tool" : "system"} size={200} />
          ))}
        </div>
      )}
    </li>
  );
}

export function TurnCard({ t, onWhole }: { t: TurnGroup; onWhole: (id: string) => void }) {
  const T = useT();
  const zh = useZh();
  const [open, setOpen] = useState(t.calls <= 1);
  const took = t.ts1 > t.ts0 ? t.ts1 - t.ts0 : 0;
  const multi = t.calls > 1;
  const last = t.steps[t.steps.length - 1];
  const replyFiles = last ? partsOf(last.reply.content).files : [];
  return (
    <div className="rounded-lg border border-line bg-panel p-3">
      <div className="flex flex-wrap items-center gap-2 text-[12px] text-ink-3">
        <span>{when(t.ts0)}</span>
        <Who id={t.account_id} hint={t.hint} />
        <PlatformPill platform={t.platform} />
        {t.run && t.run !== "person" && <Pill tone="cyan">{nameOf(T.da.runs, t.run)}</Pill>}
        {t.sources.includes("own") && <Pill>{nameOf(T.da.sources, "own")}</Pill>}
        {t.models.map((m) => (
          <code key={m} className="rounded px-1" style={{ background: "var(--panel-2)", color: modelColor(m) }}>
            {m}
          </code>
        ))}
        <Pill tone={multi ? "violet" : ""}>{multi ? T.tu.steps(t.calls) : T.tu.oneStep}</Pill>
        {t.tools.length > 0 && <span title={t.tools.join(", ")}>{T.tu.calledTools(t.tools.length)}</span>}
        <span>{T.tu.tokens(compact(t.prompt_tokens), compact(t.completion_tokens))}</span>
        {took > 0 && <span>{T.tu.took(dur(took, zh))}</span>}
        {t.media > 0 && <span>{`${T.tu.picture} ${t.media}`}</span>}
        {t.partial > 0 && <Pill tone="warn">{T.tu.partial}</Pill>}
        {t.script && <Pill tone="violet" title={t.trajectory}>{t.script}</Pill>}
        {t.conversation && <code className="opacity-60" title={T.tu.conversation}>{t.conversation.slice(0, 8)}</code>}
      </div>
      <div className="mt-2 flex flex-col gap-2">
        {t.person ? <MessageView m={t.person} label={<span className="font-medium text-accent">{T.tu.person}</span>} tone="person" size={220} /> : <div className="hint">{T.tu.noPerson}</div>}
        {multi && (
          <button type="button" className="self-start text-[12.5px] text-accent" onClick={() => setOpen((v) => !v)}>
            {open ? T.tu.fold : `${T.tu.expand} · ${T.tu.steps(t.calls)}`}
          </button>
        )}
        {open && (
          <ol className="flex flex-col gap-3">
            {t.steps.map((s, i) => (
              <StepView key={s.call.id} step={s} i={i + 1} n={t.steps.length} onWhole={onWhole} />
            ))}
          </ol>
        )}
        {!open && (
          <div className="rounded-lg border border-ok/30 bg-ok-soft/30 px-3 py-2">
            <div className="mb-1 text-[11.5px] font-medium text-ok">{T.tu.reply}</div>
            {t.reply ? <Clamped text={t.reply} /> : <span className="hint">{T.tu.noReply}</span>}
            <Files files={replyFiles} />
          </div>
        )}
      </div>
    </div>
  );
}

/** One call in full, from GET /v1/admin/turns/{id}: every message the model saw, its answer,
 *  the figures and the metadata. */
export function CallDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const T = useT();
  const q = useData<{ turn: TurnFull }>(`/v1/admin/turns/${encodeURIComponent(id)}`);
  const [tab, setTab] = useState<"messages" | "meta">("messages");
  return (
    <Drawer title={T.tu.callTitle(id.length > 48 ? id.slice(0, 48) + "…" : id)} sub={id.length > 48 ? id : undefined} onClose={onClose} width={860}>
      {q.error ? (
        q.error.status === 404 ? <Empty>{T.tu.gone}</Empty> : <Failed error={q.error.message} onRetry={q.reload} />
      ) : !q.data ? (
        <Loading />
      ) : (
        (() => {
          const t = q.data.turn;
          const msgs = t.request?.messages || [];
          const tools = (t.request?.tools || []).length;
          return (
            <>
              <div className="mb-3 flex flex-wrap items-center gap-2 text-[12px] text-ink-3">
                <span>{when(t.ts)}</span>
                <Who id={t.account_id} hint={t.hint} />
                <PlatformPill platform={t.platform} />
                <code>{t.model}</code>
                {t.run && <Pill tone="cyan">{nameOf(T.da.runs, t.run)}</Pill>}
                <Pill>{nameOf(T.da.sources, t.source)}</Pill>
                <span>{T.tu.tokens(compact(t.prompt_tokens), compact(t.completion_tokens))}</span>
                <span>{T.tu.messages(msgs.length)}</span>
                {tools > 0 && <span>{T.tu.tools(tools)}</span>}
                {t.status && t.status !== "ok" && <Pill tone="bad">{t.status}</Pill>}
                {t.turn_start !== undefined && <Pill tone={t.turn_start ? "accent" : ""}>{t.turn_start ? T.tu.opened : T.tu.continued}</Pill>}
              </div>
              <Chips options={[{ id: "messages" as const, label: T.tu.request }, { id: "meta" as const, label: T.tu.meta }]} value={tab} onChange={setTab} className="mb-3" />
              {tab === "messages" ? (
                <div className="flex flex-col gap-2">
                  {msgs.map((m, i) => (
                    <MessageView key={i} m={m} label={<><span className="font-medium">{nameOf(T.tu.roles, m.role)}</span>{m.name && <code>{m.name}</code>}{m.tool_call_id && <code className="opacity-60">{m.tool_call_id}</code>}</>} size={220} />
                  ))}
                  <div className="mt-2 text-[12px] font-medium text-ok">{T.tu.response}</div>
                  {t.response?.message ? <MessageView m={t.response.message} tone="model" size={220} /> : <div className="hint">{T.tu.noReply}</div>}
                </div>
              ) : (
                <pre className="mono max-h-[70vh] overflow-auto rounded-lg border border-line bg-panel-2 p-3 text-[12px] whitespace-pre-wrap break-words">
                  {JSON.stringify({ meta: t.meta, usage: t.response?.usage, finish_reason: t.response?.finish_reason, device: t.device, conversation: t.conversation, turn: t.turn, step: t.step, trajectory: t.trajectory, trajectory_step: t.trajectory_step, script: t.script, turn_key: t.turn_key, media: t.media, media_bytes: t.media_bytes }, null, 2)}
                </pre>
              )}
            </>
          );
        })()
      )}
    </Drawer>
  );
}

// -- the page --------------------------------------------------------------------------------------

type Filters = { account_id: string; platform: string; run: string; source: string; model: string; script: string; media: string; hands: string; multi: string };

function useTurnPages(query: string) {
  const [pages, setPages] = useState<TurnGroups[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  // a page asked for under an older filter (a "More" still in flight when the filter
  // changed) must not land under the new one, nor clear its loading flag
  const requests = useRef(new LatestRequest());
  const load = useCallback(
    (after?: TurnGroup) => requests.current.run(
      () => {
        const extra = after ? `&before=${after.ts1}&before_key=${encodeURIComponent(after.key)}` : "";
        return get<TurnGroups>(`/v1/admin/record/turns?${query}${extra}`);
      },
      {
        start: () => { setLoading(true); setError(""); },
        success: (page) => {
          setPages((p) => (after ? [...p, page] : [page]));
          if (page.turns.length < PAGE) setDone(true);
        },
        error: (e) => setError(e instanceof Error ? e.message : String(e)),
        finish: () => setLoading(false),
      },
    ),
    [query],
  );
  useEffect(() => {
    const pending = requests.current;
    setPages([]);
    setDone(false);
    void load();
    return () => pending.invalidate();
  }, [load]);
  const turns = useMemo(() => pages.flatMap((p) => p.turns), [pages]);
  const last = turns[turns.length - 1];
  return { turns, total: pages[0]?.total ?? 0, pending: pages[0]?.pending ?? 0, loading, error, done, more: () => (last ? load(last) : load()), reload: () => load() };
}

export function Turns({ days }: PageProps) {
  const T = useT();
  const route = useRoute();
  const f: Filters = {
    account_id: route.params.get("account") || "",
    platform: route.params.get("platform") || "",
    run: route.params.get("run") || "",
    source: route.params.get("source") || "",
    model: route.params.get("model") || "",
    script: route.params.get("script") || "",
    media: route.params.get("media") || "",
    hands: route.params.get("hands") || "",
    multi: route.params.get("multi") || "",
  };
  const [account, setAccount] = useState(f.account_id);
  const [model, setModel] = useState(f.model);
  const [script, setScript] = useState(f.script);
  const dAccount = useDebounced(account, 400);
  const dModel = useDebounced(model, 400);
  const dScript = useDebounced(script, 400);
  const setRoute = route.set;
  useEffect(() => {
    setRoute({ account: dAccount || null, model: dModel || null, script: dScript || null }, true);
  }, [dAccount, dModel, dScript, setRoute]);
  // An account set from outside while the page is open (the account drawer's link): the box
  // follows the hash. A change the box itself made arrives with the debounced value and is
  // left alone, so typing is never overwritten.
  useEffect(() => {
    if (f.account_id !== dAccount) setAccount(f.account_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [f.account_id]);
  const since = useMemo(() => nowS() - days * 86400, [days]);
  const query = qs({ since, limit: PAGE, account_id: f.account_id, platform: f.platform, run: f.run, source: f.source, model: f.model, script: f.script, media: f.media ? 1 : undefined, hands: f.hands ? 1 : undefined });
  const list = useTurnPages(query);
  const figures = useData<RecordView>(`/v1/admin/record?days=${days}`, { poll: 300_000 });
  const [whole, setWhole] = useState<string | null>(null);
  const shown = f.multi ? list.turns.filter((t) => t.calls > 1) : list.turns;
  const filtered = Object.values(f).some(Boolean);
  const chip = (key: keyof Filters, options: { id: string; label: string }[]) => <Chips options={[{ id: "", label: T.tu.any }, ...options]} value={f[key]} onChange={(v) => route.set({ [key === "account_id" ? "account" : key]: v || null }, true)} />;
  return (
    <>
      <Note>{T.tu.intro}</Note>
      <Loaded q={figures}>
        {(r) => {
          const qn = r.questions;
          const buckets = Object.entries(qn.calls_per_question || {});
          return (
            <>
              <Kpis>
                <Kpi label={T.tu.questions} value={fmt(r.period.questions)} sub={`${fmt(r.totals.questions)} / ${fmt(r.totals.n)}`} tone="accent" />
                <Kpi label={T.tu.calls} value={fmt(r.period.n)} sub={T.g.period(days)} />
                <Kpi label={T.tu.perQuestion} value={qn.calls_mean ? qn.calls_mean.toFixed(1) : "–"} sub={T.tu.perQuestionSub(qn.calls_mean ? qn.calls_mean.toFixed(2) : "0")} />
                <Kpi label={T.tu.withMedia} value={fmt(qn.with_media)} tone="violet" />
                <Kpi label={T.tu.withHands} value={fmt(qn.with_hands)} />
                <Kpi label={T.tu.pending} value={fmt(qn.pending)} sub={qn.pending ? T.tu.pendingSub : undefined} tone={qn.pending ? "warn" : undefined} />
              </Kpis>
              {buckets.length > 0 && (
                <Panel title={T.tu.histogram}>
                  <Ranks rows={buckets.map(([b, n]) => ({ name: T.tu.bucket(b), value: n, color: b === "1" ? "var(--c1)" : "var(--c3)" }))} showShare />
                </Panel>
              )}
            </>
          );
        }}
      </Loaded>
      <Panel
        title={filtered ? T.tu.shownSome(shown.length) : list.total ? T.tu.shown(shown.length, list.total) : T.tu.questions}
        sub={list.pending > 0 ? T.da.pendingTurns(list.pending) : undefined}
        right={
          <div className="flex flex-wrap items-center gap-2">
            <Search value={account} onChange={setAccount} placeholder={T.tu.accountHint} className="w-44" />
            <Search value={model} onChange={setModel} placeholder={T.tu.modelHint} className="w-40" />
            <Search value={script} onChange={setScript} placeholder={T.tu.scriptHint} className="w-36" />
          </div>
        }
      >
        <div className="mb-3 flex flex-col gap-2 text-[12.5px]">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <span className="hint w-16">{T.tu.filters.platform}</span>
            {chip("platform", ["android", "ios", "desktop", "runtime", "browser"].map((p) => ({ id: p, label: nameOf(T.platforms, p) })))}
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <span className="hint w-16">{T.tu.filters.run}</span>
            {chip("run", ["person", "schedule", "feed", "goal", "hub"].map((r) => ({ id: r, label: nameOf(T.da.runs, r) })))}
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <span className="hint w-16">{T.tu.filters.source}</span>
            {chip("source", ["cloud", "own"].map((s) => ({ id: s, label: nameOf(T.da.sources, s) })))}
            <Chips
              className="ml-2"
              options={[{ id: "", label: T.g.all }, { id: "media", label: T.tu.onlyMedia }, { id: "hands", label: T.tu.onlyHands }, { id: "multi", label: T.tu.multi }]}
              value={f.media ? "media" : f.hands ? "hands" : f.multi ? "multi" : ""}
              onChange={(v) => route.set({ media: v === "media" ? 1 : null, hands: v === "hands" ? 1 : null, multi: v === "multi" ? 1 : null }, true)}
            />
          </div>
        </div>
        {list.error ? (
          <Failed error={list.error} onRetry={list.reload} />
        ) : (
          <div className="flex flex-col gap-3">
            {shown.map((t) => (
              <TurnCard key={t.key} t={t} onWhole={setWhole} />
            ))}
            {!list.loading && !shown.length && <Empty />}
            {list.loading && <Loading />}
            {!list.loading && !list.done && (
              <Btn className="self-center" onClick={() => void list.more()}>
                {T.tu.more}
              </Btn>
            )}
            {!list.loading && list.done && shown.length > 0 && <div className="hint py-2 text-center">{T.tu.noMore}</div>}
          </div>
        )}
      </Panel>
      {whole && <CallDrawer id={whole} onClose={() => setWhole(null)} />}
    </>
  );
}
