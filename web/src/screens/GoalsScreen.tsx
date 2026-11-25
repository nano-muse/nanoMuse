import {
  Bell,
  BellRing,
  CalendarDays,
  CheckCircle2,
  Circle,
  CircleDashed,
  CircleSlash,
  MessageCircle,
  MoreVertical,
  OctagonAlert,
  Pause,
  Play,
  Plus,
  Sparkles,
  Square,
  SquareCheck,
  Trash2,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api";
import { MuseRoundButton } from "../components/MuseHeader";
import { Sheet } from "../components/Sheet";
import { StarNudgeOnce } from "../components/StarNudge";
import { TabHeader } from "../components/TabHeader";
import { useT } from "../i18n";
import { CADENCES, CATEGORIES, WEEKDAYS, categoryOf, describeCadence, dueLabel, joinCadence, ordinal, splitCadence, weekdayName } from "../goals";
import { useStore } from "../store";
import type { Goal, GoalCategory, GoalStep } from "../types";
import { cx, relativeTime, timeShort } from "../util";

const STEP_ICON: Record<GoalStep["status"], (p: { size: number; className?: string }) => ReactNode> = {
  pending: (p) => <Circle {...p} />,
  in_progress: (p) => <CircleDashed {...p} className={cx(p.className, "text-accent")} />,
  done: (p) => <CheckCircle2 {...p} className={cx(p.className, "text-emerald-500")} />,
  blocked: (p) => <OctagonAlert {...p} className={cx(p.className, "text-rose-500")} />,
  skipped: (p) => <CircleSlash {...p} className={cx(p.className, "text-muted")} />,
};

const STEP_NEXT: Record<GoalStep["status"], GoalStep["status"]> = {
  pending: "done",
  in_progress: "done",
  done: "pending",
  blocked: "pending",
  skipped: "pending",
};

export function GoalsScreen() {
  const { state, refreshGoals, send, openThread, toast } = useStore();
  const [selected, setSelected] = useState<string | null>(state.focusedGoalId);
  const [creating, setCreating] = useState(false);
  const [sheetCategory, setSheetCategory] = useState<(typeof CATEGORIES)[number] | null>(null);
  const [allFinished, setAllFinished] = useState(false);
  const createRef = useRef<HTMLDivElement>(null);
  const name = state.profile?.name ?? "nanoMuse";
  const t = useT();

  useEffect(() => {
    void refreshGoals();
  }, [refreshGoals]);

  const proposals = state.goals.filter((g) => g.proposal && g.status !== "cancelled");
  // Muse lists everything it is tracking in one place: the live goals first, the paused ones after.
  const tracked = [...state.goals.filter((g) => g.status === "active"), ...state.goals.filter((g) => g.status === "paused")];
  const finished = state.goals.filter((g) => g.status === "done" || g.status === "cancelled");
  const goal = state.goals.find((g) => g.id === selected) ?? null;

  const advance = async (g: Goal) => {
    try {
      await api.advanceGoal(g.id);
      toast(t("{name} is working on “{title}” in the main chat", { name, title: g.title }));
      openThread("main");
    } catch (e) {
      toast((e as Error).message);
    }
  };

  // a goal just marked done: the moment for a word about a star (contract C1), when the policy allows
  const [goalDone, setGoalDone] = useState(false);
  const toggleDone = async (g: Goal) => {
    try {
      const done = g.status !== "done";
      await api.patchGoal(g.id, { status: done ? "done" : "active" });
      if (done) setGoalDone(true);
      void refreshGoals();
    } catch (e) {
      toast((e as Error).message);
    }
  };

  /** The category sheet's "Start": the goal is shaped in the chat, the way Muse does it. */
  const startGoal = (c: (typeof CATEGORIES)[number]) => {
    setSheetCategory(null);
    send(
      "main",
      t("I'd like to create a {category} goal. Ask me a few short questions, one at a time (what exactly I want, why and by when, how often to check in), then create it with concrete steps using the goals tool.", {
        category: t(c.label),
      }),
    ).catch((e: Error) => toast(e.message || t("Could not send")));
    openThread("main");
  };

  // Muse's Goals page: "Tracking" (goals with a checkbox and a two-line status), then
  // "Create a goal" with its categories.
  return (
    <div className="flex h-full flex-col">
      <TabHeader title={t("Goals")}>
        <MuseRoundButton small onClick={() => setCreating(true)} label={t("New goal")}>
          <Plus size={22} />
        </MuseRoundButton>
      </TabHeader>

      <div className="flex-1 overflow-y-auto pb-6">
        {proposals.length > 0 && (
          <section className="px-4 pb-2">
            <div className="px-1 mb-2 text-[12px] font-semibold uppercase tracking-wide text-muted">{t("{name} suggests", { name })}</div>
            <div className="space-y-2.5">
              {proposals.map((g) => (
                <ProposalCard key={g.id} goal={g} onChanged={refreshGoals} onOpen={() => setSelected(g.id)} />
              ))}
            </div>
          </section>
        )}

        <StarNudgeOnce moment="goal_done" due={goalDone} className="mx-4 mb-3" />
        <SectionHeader label={t("Tracking")} dot onAdd={() => createRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })} />
        {tracked.length === 0 ? (
          <p className="px-5 pb-3 text-[13px] text-muted">{t("Nothing tracked yet")}</p>
        ) : (
          tracked.map((g) => <GoalRow key={g.id} goal={g} onOpen={() => setSelected(g.id)} onToggle={() => void toggleDone(g)} />)
        )}

        {finished.length > 0 && (
          <>
            <div className="h-1.5" />
            <SectionHeader label={t("Finished")} />
            {(allFinished ? finished : finished.slice(0, 2)).map((g) => (
              <GoalRow key={g.id} goal={g} onOpen={() => setSelected(g.id)} onToggle={() => void toggleDone(g)} />
            ))}
            {!allFinished && finished.length > 2 && (
              <button type="button" onClick={() => setAllFinished(true)} className="px-5 py-2 text-[13.5px] font-medium text-accent">
                {t("Show {n} more", { n: finished.length - 2 })}
              </button>
            )}
          </>
        )}

        <div ref={createRef} className="mt-2.5 border-t border-border/70 px-5 pt-3.5 pb-1.5">
          <h3 className="text-[17px] font-semibold">{t("Create a goal")}</h3>
          <p className="mt-1 text-[13px] leading-[18px] text-muted">{t("Pick a category and tell me the goal you have in mind. I'll shape a plan with you and keep improving it as you go.")}</p>
        </div>
        {CATEGORIES.map((c) => (
          <button key={c.id} type="button" onClick={() => setSheetCategory(c)} className="flex h-[50px] w-full items-center gap-3.5 pl-5 pr-2 text-left active:bg-surface-2/70">
            <span className="text-fg">{c.icon({ size: 22 })}</span>
            <span className="flex-1 text-[15px] font-medium">{t(c.label)}</span>
            <span className="flex h-10 w-10 items-center justify-center text-muted">
              <Plus size={22} />
            </span>
          </button>
        ))}
      </div>

      <GoalDetail goal={goal} onClose={() => setSelected(null)} onAdvance={advance} onChanged={refreshGoals} />
      <NewGoalSheet
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={() => {
          setCreating(false);
          void refreshGoals();
        }}
      />
      <Sheet open={sheetCategory !== null} onClose={() => setSheetCategory(null)}>
        {sheetCategory && (
          <div className="px-1 pb-2">
            <h3 className="text-[20px] font-bold">{t("Create a {category} goal", { category: t(sheetCategory.label) })}</h3>
            <p className="mt-3.5 text-[15px] leading-[22px]">{t("First, we'll shape the goal together in the chat. I'll ask a few questions so I understand exactly what you're after.")}</p>
            <p className="mt-3.5 text-[15px] leading-[22px]">{t("Once it's set, I'll track your progress here.")}</p>
            <button type="button" onClick={() => startGoal(sheetCategory)} className="mt-6 flex h-[50px] w-full items-center justify-center gap-2 rounded-full bg-accent text-[16px] font-semibold text-accent-fg">
              <MessageCircle size={18} /> {t("Start")}
            </button>
          </div>
        )}
      </Sheet>
    </div>
  );
}

/** Muse's section header: an optional dot, the label, a "+" at the end. */
function SectionHeader({ label, dot = false, onAdd }: { label: string; dot?: boolean; onAdd?: () => void }) {
  return (
    <div className="flex items-center pl-5 pr-2 pt-1">
      {dot && <span className="mr-2.5 h-2 w-2 rounded-full bg-emerald-500" />}
      <span className={cx("flex-1 text-[15px] font-semibold", dot && "text-emerald-600 dark:text-emerald-400")}>{label}</span>
      {onAdd ? (
        <button type="button" onClick={onAdd} aria-label={label} className="flex h-10 w-10 items-center justify-center text-muted">
          <Plus size={22} />
        </button>
      ) : (
        <span className="h-10" />
      )}
    </div>
  );
}

function CategoryBadge({ id, size = "sm" }: { id: GoalCategory; size?: "sm" | "md" }) {
  const t = useT();
  const c = categoryOf(id);
  if (!c) return null;
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full font-medium", c.tone, size === "sm" ? "px-2 py-0.5 text-[11.5px]" : "px-2.5 py-1 text-[12.5px]")}>
      {c.icon({ size: size === "sm" ? 11 : 13 })} {t(c.label)}
    </span>
  );
}

/** One goal the way Muse lists it: a checkbox, the title, a two-line status, the cadence and progress. */
function GoalRow({ goal, onOpen, onToggle }: { goal: Goal; onOpen: () => void; onToggle: () => void }) {
  const t = useT();
  const done = goal.status === "done";
  const pct = goal.progress.total ? Math.round((goal.progress.done / goal.progress.total) * 100) : 0;
  const due = dueLabel(goal.due, goal.overdue);
  const subtitle = goal.next_step ? t("Next: {step}", { step: goal.next_step }) : goal.description || "";
  const cadence =
    goal.status === "paused"
      ? t("Paused")
      : goal.status === "cancelled"
        ? t("Cancelled")
        : done
          ? t("Done")
          : goal.check_in
            ? describeCadence(goal.check_in)
            : t("Updated {when}", { when: relativeTime(goal.updated_at) });
  return (
    <div className="flex items-start pl-[18px] pr-1 pt-2 pb-2.5">
      <button type="button" onClick={onToggle} aria-label={done ? t("Mark as not done") : t("Mark as done")} className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center text-muted">
        {done ? <SquareCheck size={22} /> : <Square size={22} />}
      </button>
      <button type="button" onClick={onOpen} className="ml-2.5 min-w-0 flex-1 pt-[3px] text-left">
        <span className={cx("line-clamp-2 block text-[15px] font-semibold leading-snug", done && "text-muted")}>{goal.title}</span>
        {subtitle && <span className="mt-0.5 line-clamp-2 block text-[13px] leading-[18px] text-muted">{subtitle}</span>}
        <span className="mt-0.5 flex items-center gap-2 text-[12px] text-muted">
          <span className="truncate">
            {cadence}
            {due && goal.status === "active" ? ` · ${due}` : ""}
          </span>
          {pct > 0 && !done && <span className="shrink-0 font-medium text-emerald-600 dark:text-emerald-400">{pct}%</span>}
        </span>
      </button>
      <button type="button" onClick={onOpen} aria-label={t("More")} className="flex h-10 w-10 shrink-0 items-center justify-center text-muted">
        <MoreVertical size={20} />
      </button>
    </div>
  );
}

/** "Muse suggests adjusting the plan" — accept swaps the open steps, dismiss keeps the plan. */
function ProposalCard({ goal, onChanged, onOpen }: { goal: Goal; onChanged: () => void; onOpen: () => void }) {
  const { toast, state } = useStore();
  const [busy, setBusy] = useState(false);
  const name = state.profile?.name ?? "nanoMuse";
  const t = useT();
  const p = goal.proposal;
  if (!p) return null;
  const act = async (accept: boolean) => {
    setBusy(true);
    try {
      if (accept) await api.acceptProposal(goal.id);
      else await api.dismissProposal(goal.id);
      toast(accept ? t("Plan updated") : t("Kept your plan"));
      onChanged();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const kept = goal.steps.filter((s) => s.status === "done" || s.status === "skipped").length;
  return (
    <div className="rounded-3xl border border-accent/30 bg-accent/5 px-4 py-3.5">
      <button type="button" onClick={onOpen} className="w-full text-left">
        <div className="flex items-center gap-2 text-[12px] font-semibold uppercase tracking-wide text-accent">
          <Sparkles size={13} /> {t("Adjust the plan for “{title}”?", { title: goal.title })}
        </div>
        <p className="mt-1.5 text-[14px] leading-snug">{p.reason}</p>
        <div className="mt-2 text-[12px] text-muted">
          {kept > 0 && <span>{kept === 1 ? t("Keeps the 1 step already done.") : t("Keeps the {n} steps already done.", { n: kept })} </span>}
          {t("New remaining steps:")}
        </div>
        <ol className="mt-1 space-y-0.5 text-[13.5px] list-decimal pl-5">
          {p.steps.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ol>
      </button>
      <div className="mt-3 flex gap-2">
        <button type="button" disabled={busy} onClick={() => void act(false)} className="flex-1 rounded-2xl border border-border py-2 text-[13.5px] font-medium disabled:opacity-50">
          {t("Keep my plan")}
        </button>
        <button type="button" disabled={busy} onClick={() => void act(true)} className="flex-1 rounded-2xl bg-accent text-accent-fg py-2 text-[13.5px] font-medium disabled:opacity-50">
          {t("Use {name}'s plan", { name })}
        </button>
      </div>
    </div>
  );
}

function CategoryPicker({ value, onChange }: { value: GoalCategory; onChange: (v: GoalCategory) => void }) {
  const t = useT();
  return (
    <div className="flex flex-wrap gap-1.5">
      {CATEGORIES.map((c) => (
        <button
          key={c.id}
          type="button"
          onClick={() => onChange(value === c.id ? "" : c.id)}
          className={cx(
            "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[12.5px] font-medium transition border",
            value === c.id ? cx(c.tone, "border-transparent ring-2 ring-accent/40") : "border-border text-muted",
          )}
        >
          {c.icon({ size: 12 })} {t(c.label)}
        </button>
      ))}
    </div>
  );
}

function CadencePicker({ value, onChange }: { value: string; onChange: (spec: string) => void }) {
  const t = useT();
  const { cadence, anchor, time } = splitCadence(value);
  const set = (c: string, a: string, at: string) => onChange(joinCadence(c, a, at));
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        {CADENCES.map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => set(c.id, c.id === "weekly" ? anchor || "mon" : c.id === "monthly" ? anchor || "1" : "", time)}
            className={cx(
              "rounded-full px-2.5 py-1 text-[12.5px] font-medium border transition",
              cadence === c.id ? "bg-accent text-accent-fg border-transparent" : "border-border text-muted",
            )}
          >
            {t(c.label)}
          </button>
        ))}
      </div>
      {cadence && (
        <div className="flex items-center gap-2 text-[13.5px]">
          {cadence === "weekly" && (
            <select value={anchor || "mon"} onChange={(e) => set(cadence, e.target.value, time)} aria-label={t("Weekday")} className="rounded-xl bg-surface-2 px-2.5 py-1.5 outline-none">
              {WEEKDAYS.map((d) => (
                <option key={d} value={d}>
                  {weekdayName(d)}
                </option>
              ))}
            </select>
          )}
          {cadence === "monthly" && (
            <select value={anchor || "1"} onChange={(e) => set(cadence, e.target.value, time)} aria-label={t("Day of the month")} className="rounded-xl bg-surface-2 px-2.5 py-1.5 outline-none">
              {Array.from({ length: 28 }, (_, i) => String(i + 1)).map((d) => (
                <option key={d} value={d}>
                  {ordinal(Number(d))}
                </option>
              ))}
            </select>
          )}
          <span className="text-muted">{t("at")}</span>
          <input type="time" value={time} onChange={(e) => set(cadence, anchor, e.target.value || "09:00")} aria-label={t("Time")} className="rounded-xl bg-surface-2 px-2.5 py-1.5 outline-none" />
        </div>
      )}
    </div>
  );
}

function GoalDetail({
  goal,
  onClose,
  onAdvance,
  onChanged,
}: {
  goal: Goal | null;
  onClose: () => void;
  onAdvance: (g: Goal) => void;
  onChanged: () => void;
}) {
  const { toast, send, openThread, state } = useStore();
  const [newStep, setNewStep] = useState("");
  const [editing, setEditing] = useState(false);
  const name = state.profile?.name ?? "nanoMuse";
  const t = useT();

  const patch = async (body: Record<string, unknown>) => {
    if (!goal) return;
    try {
      await api.patchGoal(goal.id, body);
      onChanged();
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const addStep = async () => {
    if (!goal || !newStep.trim()) return;
    try {
      await api.addStep(goal.id, newStep.trim());
      setNewStep("");
      onChanged();
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const checkIn = async () => {
    if (!goal) return;
    try {
      await api.checkInGoal(goal.id);
      toast(t("{name} will check in with you in the main chat", { name }));
      openThread("main");
      onClose();
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const remove = async () => {
    if (!goal || !window.confirm(t("Delete “{title}”?", { title: goal.title }))) return;
    try {
      await api.deleteGoal(goal.id);
      onChanged();
      onClose();
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const due = goal ? dueLabel(goal.due, goal.overdue) : "";

  return (
    <Sheet
      open={!!goal}
      onClose={onClose}
      title={goal?.title}
      footer={
        goal && (
          <div className="flex gap-2">
            {goal.status === "active" ? (
              <button type="button" onClick={() => void patch({ status: "paused" })} className="flex-1 rounded-2xl border border-border py-2.5 font-medium flex items-center justify-center gap-1.5">
                <Pause size={16} /> {t("Pause")}
              </button>
            ) : goal.status === "paused" ? (
              <button type="button" onClick={() => void patch({ status: "active" })} className="flex-1 rounded-2xl border border-border py-2.5 font-medium flex items-center justify-center gap-1.5">
                <Play size={16} /> {t("Resume")}
              </button>
            ) : null}
            {goal.status === "active" && (
              <button type="button" onClick={() => onAdvance(goal)} className="flex-1 rounded-2xl bg-accent text-accent-fg py-2.5 font-medium flex items-center justify-center gap-1.5">
                <Play size={16} /> {t("Work on it now")}
              </button>
            )}
            <button type="button" onClick={() => void remove()} aria-label={t("Delete goal")} className="rounded-2xl border border-border px-3 text-muted hover:text-rose-500">
              <Trash2 size={18} />
            </button>
          </div>
        )
      }
    >
      {goal && (
        <div className="space-y-4">
          {goal.proposal && <ProposalCard goal={goal} onChanged={onChanged} onOpen={() => undefined} />}
          {goal.description && <p className="text-[14px] text-muted leading-snug">{goal.description}</p>}

          {/* category · due · reminders */}
          <div className="rounded-2xl bg-surface-2/60 px-3.5 py-3">
            {!editing ? (
              <button type="button" onClick={() => setEditing(true)} className="w-full text-left">
                <div className="flex flex-wrap items-center gap-1.5 text-[12.5px]">
                  {goal.category ? <CategoryBadge id={goal.category} size="md" /> : <span className="rounded-full border border-dashed border-border px-2.5 py-1 text-muted">{t("No category")}</span>}
                  <span className={cx("inline-flex items-center gap-1 rounded-full px-2.5 py-1", goal.overdue ? "bg-rose-500/12 text-rose-600 dark:text-rose-300 font-medium" : "bg-surface text-muted")}>
                    <CalendarDays size={13} /> {due || t("No target date")}
                  </span>
                  <span className="inline-flex items-center gap-1 rounded-full bg-surface px-2.5 py-1 text-muted">
                    <Bell size={13} /> {goal.check_in ? describeCadence(goal.check_in) : t("No reminders")}
                  </span>
                </div>
                {goal.next_check_in && goal.status === "active" && (
                  <div className="mt-1.5 text-[12px] text-muted">{t("Next check-in {when}", { when: relativeTime(goal.next_check_in) })} · {timeShort(goal.next_check_in)}</div>
                )}
                <div className="mt-1.5 text-[12px] text-accent font-medium">{t("Edit")}</div>
              </button>
            ) : (
              <div className="space-y-3">
                <div>
                  <div className="text-[12px] font-semibold uppercase tracking-wide text-muted mb-1.5">{t("Area of life")}</div>
                  <CategoryPicker value={goal.category} onChange={(v) => void patch({ category: v })} />
                </div>
                <div>
                  <div className="text-[12px] font-semibold uppercase tracking-wide text-muted mb-1.5">{t("Target date")}</div>
                  <div className="flex items-center gap-2">
                    <input type="date" value={goal.due} onChange={(e) => void patch({ due: e.target.value })} aria-label={t("Target date")} className="rounded-xl bg-surface px-2.5 py-1.5 text-[13.5px] outline-none" />
                    {goal.due && (
                      <button type="button" onClick={() => void patch({ due: "" })} className="text-[12.5px] text-muted">
                        {t("Clear")}
                      </button>
                    )}
                  </div>
                </div>
                <div>
                  <div className="text-[12px] font-semibold uppercase tracking-wide text-muted mb-1.5">{t("Reminders from {name}", { name })}</div>
                  <CadencePicker value={goal.check_in} onChange={(spec) => void patch({ check_in: spec })} />
                </div>
                <button type="button" onClick={() => setEditing(false)} className="text-[12.5px] text-accent font-medium">
                  {t("Done")}
                </button>
              </div>
            )}
          </div>

          <div>
            <div className="text-[12px] font-semibold uppercase tracking-wide text-muted mb-2">
              {t("Plan")} · {goal.progress.done}/{goal.progress.total}
            </div>
            <ul className="space-y-1">
              {goal.steps.map((s) => {
                const Icon = STEP_ICON[s.status];
                return (
                  <li key={s.idx} className="flex items-start gap-2.5 rounded-2xl px-2 py-1.5 hover:bg-surface-2/60">
                    <button
                      type="button"
                      aria-label={t("Mark step {n} {status}", { n: s.idx, status: t(STEP_NEXT[s.status]) })}
                      onClick={() => void patch({ step_index: s.idx, step_status: STEP_NEXT[s.status] })}
                      className="mt-0.5 text-muted"
                    >
                      <Icon size={20} />
                    </button>
                    <div className="flex-1 min-w-0">
                      <div className={cx("text-[14.5px] leading-snug", (s.status === "done" || s.status === "skipped") && "line-through text-muted")}>
                        {s.idx}. {s.title}
                      </div>
                      {s.note && <div className="text-[12.5px] text-muted mt-0.5 whitespace-pre-wrap">{s.note}</div>}
                    </div>
                  </li>
                );
              })}
            </ul>
            <div className="mt-2 flex gap-2">
              <input
                value={newStep}
                onChange={(e) => setNewStep(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && void addStep()}
                placeholder={t("Add a step")}
                aria-label={t("Add a step")}
                className="flex-1 rounded-2xl bg-surface-2 px-3.5 py-2 text-[14px] outline-none focus:ring-2 focus:ring-accent/40"
              />
              <button type="button" onClick={() => void addStep()} className="rounded-2xl bg-surface-2 px-3 text-accent" aria-label={t("Add step")}>
                <Plus size={18} />
              </button>
            </div>
          </div>
          {goal.notes && (
            <div>
              <div className="text-[12px] font-semibold uppercase tracking-wide text-muted mb-1.5">{t("Notes from {name}", { name })}</div>
              <pre className="whitespace-pre-wrap break-words text-[13px] leading-snug text-muted font-sans">{goal.notes}</pre>
            </div>
          )}
          <div className="flex flex-wrap gap-x-4 gap-y-1.5">
            <button
              type="button"
              onClick={() => {
                send("main", t("About my goal “{title}” ({id}): what's the status, and what should we do next?", { title: goal.title, id: goal.id })).catch((e: Error) => toast(e.message || t("Could not send")));
                openThread("main");
                onClose();
              }}
              className="text-[13.5px] text-accent font-medium"
            >
              {t("Discuss this goal in chat →")}
            </button>
            {goal.status === "active" && (
              <button type="button" onClick={() => void checkIn()} className="text-[13.5px] text-accent font-medium inline-flex items-center gap-1">
                <BellRing size={14} /> {t("Check in with me now")}
              </button>
            )}
          </div>
        </div>
      )}
    </Sheet>
  );
}

function NewGoalSheet({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: () => void }) {
  const { toast, send, openThread, state } = useStore();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [steps, setSteps] = useState("");
  const [category, setCategory] = useState<GoalCategory>("");
  const [due, setDue] = useState("");
  const [checkIn, setCheckIn] = useState("");
  const [busy, setBusy] = useState(false);
  const name = state.profile?.name ?? "nanoMuse";
  const t = useT();

  const reset = () => {
    setTitle("");
    setDescription("");
    setSteps("");
    setCategory("");
    setDue("");
    setCheckIn("");
  };

  const create = async () => {
    if (!title.trim()) return;
    setBusy(true);
    try {
      await api.createGoal({
        title: title.trim(),
        description: description.trim(),
        steps: steps.split("\n").map((s) => s.trim()).filter(Boolean),
        category,
        due,
        check_in: checkIn,
      });
      reset();
      onCreated();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const askMuse = () => {
    if (!title.trim()) return;
    const extras = [
      category ? `category: ${category}` : "",
      due ? `target date: ${due}` : "",
      checkIn ? `check_in "${checkIn}"` : "",
    ].filter(Boolean);
    send(
      "main",
      t('Create a goal for me: "{title}"{description}{extras}. Break it into concrete steps with the goals tool, then tell me the plan.', {
        title: title.trim(),
        description: description.trim() ? ` (${description.trim()})` : "",
        extras: extras.length ? ` (${extras.join(", ")})` : "",
      }),
    ).catch((e: Error) => toast(e.message || t("Could not send")));
    reset();
    onClose();
    openThread("main");
  };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={t("New goal")}
      footer={
        <div className="flex gap-2">
          <button type="button" onClick={askMuse} disabled={!title.trim()} className="flex-1 rounded-2xl border border-border py-2.5 font-medium disabled:opacity-50 flex items-center justify-center gap-1.5">
            <Sparkles size={16} /> {t("Let {name} plan it", { name })}
          </button>
          <button type="button" onClick={() => void create()} disabled={!title.trim() || busy} className="flex-1 rounded-2xl bg-accent text-accent-fg py-2.5 font-medium disabled:opacity-50">
            {t("Create")}
          </button>
        </div>
      }
    >
      <div className="space-y-3.5">
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t("What do you want to achieve?")} aria-label={t("What do you want to achieve?")} className="w-full rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[15px] outline-none focus:ring-2 focus:ring-accent/40" />
        <div>
          <div className="text-[12px] font-semibold uppercase tracking-wide text-muted mb-1.5">{t("Area of life")}</div>
          <CategoryPicker value={category} onChange={setCategory} />
        </div>
        <div className="flex items-center gap-3">
          <div className="text-[12px] font-semibold uppercase tracking-wide text-muted flex-1">{t("Target date")}</div>
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} aria-label={t("Target date")} className="rounded-xl bg-surface-2 px-2.5 py-1.5 text-[13.5px] outline-none" />
        </div>
        <div>
          <div className="text-[12px] font-semibold uppercase tracking-wide text-muted mb-1.5">{t("Reminders from {name}", { name })}</div>
          <CadencePicker value={checkIn} onChange={setCheckIn} />
        </div>
        <textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder={t("Why it matters, constraints (optional)")} aria-label={t("Why it matters, constraints (optional)")} rows={2} className="w-full rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[14px] outline-none focus:ring-2 focus:ring-accent/40 resize-none" />
        <textarea value={steps} onChange={(e) => setSteps(e.target.value)} placeholder={t("Steps, one per line (optional, or let {name} plan them)", { name })} aria-label={t("Steps, one per line (optional, or let {name} plan them)", { name })} rows={3} className="w-full rounded-2xl bg-surface-2 px-3.5 py-2.5 text-[14px] outline-none focus:ring-2 focus:ring-accent/40 resize-none" />
      </div>
    </Sheet>
  );
}
