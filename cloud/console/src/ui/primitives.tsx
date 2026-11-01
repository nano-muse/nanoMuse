/** The shared shapes: panels, KPI cards, pills, chips, buttons, inputs, tables, drawers,
 *  modals, toasts and a tooltip. Hand-rolled on Tailwind utilities and the tokens in
 *  styles.css; no component library. */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { saveBlob } from "../lib/api";
import { toCsv } from "../lib/format";
import { useT } from "../lib/i18n";

export type Tone = "" | "ok" | "warn" | "bad" | "accent" | "violet" | "cyan";

export const cx = (...xs: (string | false | null | undefined)[]) => xs.filter(Boolean).join(" ");

// -- layout -----------------------------------------------------------------------------------

export function Panel({
  title,
  sub,
  right,
  children,
  className,
  pad = true,
  id,
}: {
  title?: ReactNode;
  sub?: ReactNode;
  right?: ReactNode;
  children?: ReactNode;
  className?: string;
  pad?: boolean;
  id?: string;
}) {
  return (
    <section id={id} className={cx("panel fade-in flex min-w-0 flex-col", className)}>
      {(title || right) && (
        <header className="flex flex-wrap items-start gap-x-3 gap-y-1 px-4 pt-3.5 pb-2">
          <div className="min-w-0 flex-1">
            {title && <h2 className="m-0 text-[15px] font-semibold tracking-tight">{title}</h2>}
            {sub && <div className="hint mt-0.5">{sub}</div>}
          </div>
          {right && <div className="flex flex-wrap items-center gap-2">{right}</div>}
        </header>
      )}
      <div className={cx("min-w-0 flex-1", pad && "px-4 pb-4", pad && !title && "pt-4")}>{children}</div>
    </section>
  );
}

export const Grid = ({ cols = 2, children, className }: { cols?: 1 | 2 | 3 | 4; children: ReactNode; className?: string }) => (
  <div className={cx("grid gap-3", cols === 1 && "grid-cols-1", cols === 2 && "grid-cols-1 xl:grid-cols-2", cols === 3 && "grid-cols-1 lg:grid-cols-3", cols === 4 && "grid-cols-2 lg:grid-cols-4", className)}>
    {children}
  </div>
);

export function Kpis({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-6", className)}>{children}</div>;
}

export function Kpi({ label, value, sub, tone = "", small, onClick, flat }: { label: ReactNode; value: ReactNode; sub?: ReactNode; tone?: Tone; small?: boolean; onClick?: () => void; flat?: boolean }) {
  const color = tone === "ok" ? "text-ok" : tone === "warn" ? "text-warn" : tone === "bad" ? "text-bad" : tone === "accent" ? "text-accent" : tone === "violet" ? "text-violet" : tone === "cyan" ? "text-cyan" : "";
  return (
    <div className={cx("kpi min-w-0", !flat && "panel px-4 py-3", flat && "px-1 py-1", onClick && "cursor-pointer hover:bg-panel-2")} onClick={onClick}>
      <div className="hint truncate">{label}</div>
      <div className={cx("v truncate", small && "sm", color)}>{value}</div>
      {sub !== undefined && <div className="sub mt-0.5 truncate">{sub}</div>}
    </div>
  );
}

export const Pill = ({ tone = "", children, className, title }: { tone?: Tone; children: ReactNode; className?: string; title?: string }) => (
  <span className={cx("pill", tone, className)} title={title}>
    {children}
  </span>
);

export const Dot = ({ color, className }: { color: string; className?: string }) => <span className={cx("inline-block h-2 w-2 rounded-full", className)} style={{ background: color }} />;

export function Btn({ variant = "", size = "", className, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "" | "primary" | "danger"; size?: "" | "sm" }) {
  return <button type="button" className={cx("btn", variant, size, className)} {...rest} />;
}

export function Chips<T extends string>({ options, value, onChange, className }: { options: { id: T; label: ReactNode; n?: number }[]; value: T; onChange: (v: T) => void; className?: string }) {
  return (
    <div className={cx("flex flex-wrap gap-1.5", className)}>
      {options.map((o) => (
        <button key={o.id} type="button" className={cx("chip", o.id === value && "on")} onClick={() => onChange(o.id)}>
          {o.label}
          {o.n !== undefined && <span className="ml-1 opacity-60">{o.n}</span>}
        </button>
      ))}
    </div>
  );
}

export function Seg<T extends string>({ options, value, onChange }: { options: { id: T; label: ReactNode }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex rounded-lg border border-line bg-panel-2 p-0.5">
      {options.map((o) => (
        <button key={o.id} type="button" className={cx("rounded-md px-2.5 py-1 text-[12.5px]", o.id === value ? "bg-panel shadow-sm font-medium" : "text-ink-2 hover:text-ink")} onClick={() => onChange(o.id)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export const Empty = ({ children, className }: { children?: ReactNode; className?: string }) => {
  const T = useT();
  return <div className={cx("hint px-2 py-8 text-center", className)}>{children ?? T.g.none}</div>;
};

export const Loading = ({ className }: { className?: string }) => {
  const T = useT();
  return (
    <div className={cx("hint px-2 py-8 text-center", className)}>
      <span className="pulse">{T.g.loading}</span>
    </div>
  );
};

export const Failed = ({ error, onRetry }: { error: string; onRetry?: () => void }) => {
  const T = useT();
  return (
    <div className="px-2 py-6 text-center">
      <div className="text-bad">{T.g.failed}</div>
      <div className="hint mt-1 break-all">{error}</div>
      {onRetry && (
        <Btn size="sm" className="mt-3" onClick={onRetry}>
          {T.g.retry}
        </Btn>
      )}
    </div>
  );
};

export function Search({ value, onChange, placeholder, className, autoFocus }: { value: string; onChange: (v: string) => void; placeholder?: string; className?: string; autoFocus?: boolean }) {
  return (
    <div className={cx("relative", className)}>
      <svg className="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-ink-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="11" cy="11" r="7" />
        <path d="m20 20-3.5-3.5" />
      </svg>
      <input type="search" className="inp w-full pl-8" value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} autoFocus={autoFocus} />
    </div>
  );
}

export function Toggle({ on, onChange, disabled, label }: { on: boolean; onChange: (v: boolean) => void; disabled?: boolean; label?: ReactNode }) {
  return (
    <label className={cx("inline-flex items-center gap-2 select-none", disabled ? "opacity-50" : "cursor-pointer")}>
      <span role="switch" aria-checked={on} className={cx("relative inline-block h-5 w-9 rounded-full transition-colors", on ? "bg-accent" : "bg-line-2")} onClick={() => !disabled && onChange(!on)}>
        <span className={cx("absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform", on ? "translate-x-4.5" : "translate-x-0.5")} />
      </span>
      {label && <span>{label}</span>}
    </label>
  );
}

export const Field = ({ label, hint, children, className }: { label: ReactNode; hint?: ReactNode; children: ReactNode; className?: string }) => (
  <label className={cx("flex min-w-0 flex-col gap-1", className)}>
    <span className="text-[12.5px] text-ink-2">{label}</span>
    {children}
    {hint && <span className="hint">{hint}</span>}
  </label>
);

export const Bar = ({ value, max, tone = "accent", className }: { value: number; max: number; tone?: Tone | string; className?: string }) => {
  const color = tone.startsWith("#") || tone.startsWith("var(") ? tone : `var(--${tone || "accent"})`;
  return (
    <div className={cx("bar-track", className)}>
      <div className="bar-fill" style={{ width: `${max > 0 ? Math.min(100, (100 * value) / max) : 0}%`, background: color }} />
    </div>
  );
};

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: ReactNode; n?: number }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div className="scroll-x flex gap-1 border-b border-line">
      {tabs.map((t) => (
        <button key={t.id} type="button" className={cx("-mb-px border-b-2 px-3 py-2 text-[13px] whitespace-nowrap", t.id === value ? "border-accent font-medium text-ink" : "border-transparent text-ink-2 hover:text-ink")} onClick={() => onChange(t.id)}>
          {t.label}
          {t.n !== undefined && <span className="ml-1.5 text-ink-3">{t.n}</span>}
        </button>
      ))}
    </div>
  );
}

export const Note = ({ children, tone = "", className }: { children: ReactNode; tone?: Tone; className?: string }) => (
  <div className={cx("rounded-lg px-3 py-2 text-[12.5px]", tone === "warn" ? "bg-warn-soft text-warn" : tone === "bad" ? "bg-bad-soft text-bad" : tone === "ok" ? "bg-ok-soft text-ok" : "bg-panel-2 text-ink-2", className)}>{children}</div>
);

export const KV = ({ rows }: { rows: [ReactNode, ReactNode][] }) => (
  <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5">
    {rows.map(([k, v], i) => (
      <div key={i} className="contents">
        <dt className="hint whitespace-nowrap">{k}</dt>
        <dd className="m-0 min-w-0 break-all">{v}</dd>
      </div>
    ))}
  </dl>
);

// -- tables -----------------------------------------------------------------------------------

export interface Col<T> {
  key: string;
  label: ReactNode;
  num?: boolean;
  hideSm?: boolean;
  width?: string;
  render?: (row: T, i: number) => ReactNode;
  value?: (row: T) => number | string | null | undefined;
  sortable?: boolean;
  csv?: (row: T) => unknown;
  wrap?: boolean;
}

/** What "shown" becomes when a poll brings a fresh list: the person's "More" survives,
 *  unless the list itself no longer reaches what they were shown. */
export const keptShown = (shown: number, limit: number | undefined, rows: number): number =>
  Math.min(shown, Math.max(limit || 0, rows));

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRow,
  defaultSort,
  defaultDesc = true,
  empty,
  maxHeight,
  selectedKey,
  className,
  limit,
  footer,
}: {
  columns: Col<T>[];
  rows: T[];
  rowKey: (row: T, i: number) => string | number;
  onRow?: (row: T) => void;
  defaultSort?: string;
  defaultDesc?: boolean;
  empty?: ReactNode;
  maxHeight?: number | string;
  selectedKey?: string | number;
  className?: string;
  limit?: number;
  footer?: ReactNode;
}) {
  const T = useT();
  const [sort, setSort] = useState<{ key: string; desc: boolean } | null>(defaultSort ? { key: defaultSort, desc: defaultDesc } : null);
  const [shown, setShown] = useState(limit || 0);
  // every poll re-creates the rows array: the person's "More" survives the refresh, and
  // gives way only when the list itself no longer reaches what they were shown
  useEffect(() => setShown((s) => keptShown(s, limit, rows.length)), [limit, rows]);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    const val = col?.value || ((r: T) => (r as Record<string, unknown>)[sort.key] as number | string | null | undefined);
    const out = [...rows];
    out.sort((a, b) => {
      const x = val(a),
        y = val(b);
      if (x === y) return 0;
      if (x === null || x === undefined || x === "") return 1;
      if (y === null || y === undefined || y === "") return -1;
      const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
      return sort.desc ? -c : c;
    });
    return out;
  }, [rows, sort, columns]);
  const visible = shown ? sorted.slice(0, shown) : sorted;
  const click = (c: Col<T>) => {
    if (c.sortable === false) return;
    setSort((s) => (s && s.key === c.key ? { key: c.key, desc: !s.desc } : { key: c.key, desc: c.num !== false }));
  };
  return (
    <div className={cx("scroll-x", className)} style={maxHeight ? { maxHeight, overflowY: "auto" } : undefined}>
      <table className="tbl">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={cx(c.num && "num", c.hideSm && "hide-sm", c.sortable !== false && "cursor-pointer select-none hover:text-ink")} style={c.width ? { width: c.width } : undefined} onClick={() => click(c)}>
                {c.label}
                {sort?.key === c.key && <span className="ml-1 text-accent">{sort.desc ? "↓" : "↑"}</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {visible.map((r, i) => {
            const k = rowKey(r, i);
            return (
              <tr key={k} className={cx(onRow && "tap", selectedKey !== undefined && selectedKey === k && "on")} onClick={onRow ? () => onRow(r) : undefined}>
                {columns.map((c) => (
                  <td key={c.key} className={cx(c.num && "num", c.hideSm && "hide-sm", c.wrap && "wrap")}>
                    {c.render ? c.render(r, i) : String((r as Record<string, unknown>)[c.key] ?? "")}
                  </td>
                ))}
              </tr>
            );
          })}
          {!visible.length && (
            <tr>
              <td colSpan={columns.length}>
                <Empty>{empty}</Empty>
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {(shown > 0 && sorted.length > shown) || footer ? (
        <div className="flex items-center gap-3 px-2 py-2">
          {shown > 0 && sorted.length > shown && (
            <Btn size="sm" onClick={() => setShown(shown + (limit || 50))}>
              {T.g.more} ({sorted.length - shown})
            </Btn>
          )}
          {footer}
        </div>
      ) : null}
    </div>
  );
}

export function CsvButton<T>({ name, columns, rows, label }: { name: string; columns: Col<T>[]; rows: T[]; label?: ReactNode }) {
  const T = useT();
  const go = () => {
    const cols = columns.map((c) => (typeof c.label === "string" ? c.label : c.key));
    const data = rows.map((r) => columns.map((c) => (c.csv ? c.csv(r) : c.value ? c.value(r) : (r as Record<string, unknown>)[c.key])));
    saveBlob(new Blob(["\ufeff" + toCsv(cols, data)], { type: "text/csv;charset=utf-8" }), `${name}.csv`);
  };
  return (
    <Btn size="sm" onClick={go} disabled={!rows.length}>
      {label ?? T.g.csv}
    </Btn>
  );
}

// -- overlays ---------------------------------------------------------------------------------

export function Modal({ title, onClose, children, footer, width = 460 }: { title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; width?: number }) {
  useEffect(() => {
    const on = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="panel fade-in max-h-full w-full overflow-auto" style={{ maxWidth: width, boxShadow: "var(--shadow-2)" }}>
        <div className="px-5 pt-4 pb-2 text-[15px] font-semibold">{title}</div>
        <div className="px-5 py-2">{children}</div>
        {footer && <div className="flex justify-end gap-2 px-5 pt-2 pb-4">{footer}</div>}
      </div>
    </div>
  );
}

export function Drawer({ title, sub, onClose, children, width = 720, right }: { title: ReactNode; sub?: ReactNode; onClose: () => void; children: ReactNode; width?: number; right?: ReactNode }) {
  const T = useT();
  useEffect(() => {
    const on = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", on);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", on);
      document.body.style.overflow = prev;
    };
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="drawer-in flex h-full w-full flex-col bg-bg" style={{ maxWidth: width, boxShadow: "var(--shadow-2)" }}>
        <header className="flex items-start gap-3 border-b border-line bg-panel px-5 py-3">
          <div className="min-w-0 flex-1">
            <div className="truncate text-[15px] font-semibold">{title}</div>
            {sub && <div className="hint truncate">{sub}</div>}
          </div>
          {right}
          <button type="button" className="btn sm" onClick={onClose} aria-label={T.g.close}>
            ✕
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-auto p-4">{children}</div>
      </div>
    </div>
  );
}

// -- confirm / prompt dialogs -------------------------------------------------------------------

interface PromptSpec {
  title: ReactNode;
  body?: ReactNode;
  fields?: { id: string; label: ReactNode; type?: "text" | "number" | "select" | "checkbox" | "textarea"; options?: { id: string; label: ReactNode }[]; value?: string | boolean; hint?: ReactNode; placeholder?: string; step?: string }[];
  danger?: boolean;
  okLabel?: ReactNode;
}
type Resolver = (v: Record<string, string | boolean> | null) => void;
const DialogContext = createContext<(spec: PromptSpec) => Promise<Record<string, string | boolean> | null>>(() => Promise.resolve(null));
export const useDialog = () => useContext(DialogContext);

export function DialogHost({ children }: { children: ReactNode }) {
  const T = useT();
  const [spec, setSpec] = useState<PromptSpec | null>(null);
  const [values, setValues] = useState<Record<string, string | boolean>>({});
  const resolver = useRef<Resolver | null>(null);
  const ask = useCallback((s: PromptSpec) => {
    return new Promise<Record<string, string | boolean> | null>((resolve) => {
      resolver.current = resolve;
      const init: Record<string, string | boolean> = {};
      for (const f of s.fields || []) init[f.id] = f.value ?? (f.type === "checkbox" ? false : "");
      setValues(init);
      setSpec(s);
    });
  }, []);
  const finish = (v: Record<string, string | boolean> | null) => {
    setSpec(null);
    resolver.current?.(v);
    resolver.current = null;
  };
  return (
    <DialogContext.Provider value={ask}>
      {children}
      {spec && (
        <Modal
          title={spec.title}
          onClose={() => finish(null)}
          footer={
            <>
              <Btn onClick={() => finish(null)}>{T.g.cancel}</Btn>
              <Btn variant={spec.danger ? "danger" : "primary"} onClick={() => finish(values)} autoFocus={!spec.fields?.length}>
                {spec.okLabel ?? T.g.confirm}
              </Btn>
            </>
          }
        >
          {spec.body && <div className="whitespace-pre-line text-ink-2">{spec.body}</div>}
          {spec.fields?.length ? (
            <div className="mt-3 flex flex-col gap-3">
              {spec.fields.map((f, i) =>
                f.type === "checkbox" ? (
                  <label key={f.id} className="flex items-center gap-2">
                    <input type="checkbox" checked={!!values[f.id]} onChange={(e) => setValues((v) => ({ ...v, [f.id]: e.target.checked }))} />
                    <span>{f.label}</span>
                  </label>
                ) : (
                  <Field key={f.id} label={f.label} hint={f.hint}>
                    {f.type === "select" ? (
                      <select className="inp" value={String(values[f.id] ?? "")} onChange={(e) => setValues((v) => ({ ...v, [f.id]: e.target.value }))}>
                        {f.options?.map((o) => (
                          <option key={o.id} value={o.id}>
                            {o.label}
                          </option>
                        ))}
                      </select>
                    ) : f.type === "textarea" ? (
                      <textarea className="inp" rows={3} value={String(values[f.id] ?? "")} placeholder={f.placeholder} onChange={(e) => setValues((v) => ({ ...v, [f.id]: e.target.value }))} />
                    ) : (
                      <input
                        className="inp"
                        type={f.type || "text"}
                        step={f.step}
                        autoFocus={i === 0}
                        value={String(values[f.id] ?? "")}
                        placeholder={f.placeholder}
                        onChange={(e) => setValues((v) => ({ ...v, [f.id]: e.target.value }))}
                        onKeyDown={(e) => e.key === "Enter" && finish(values)}
                      />
                    )}
                  </Field>
                ),
              )}
            </div>
          ) : null}
        </Modal>
      )}
    </DialogContext.Provider>
  );
}

// -- toasts -------------------------------------------------------------------------------------

const ToastContext = createContext<(msg: string, tone?: Tone) => void>(() => undefined);
export const useToast = () => useContext(ToastContext);

export function ToastHost({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<{ id: number; msg: string; tone: Tone }[]>([]);
  const next = useRef(1);
  const push = useCallback((msg: string, tone: Tone = "") => {
    const id = next.current++;
    setItems((xs) => [...xs, { id, msg, tone }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), tone === "bad" ? 7000 : 3500);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed right-4 bottom-4 z-[70] flex flex-col gap-2">
        {items.map((t) => (
          <div key={t.id} className={cx("fade-in rounded-lg px-3.5 py-2 text-[13px] shadow-lg", t.tone === "bad" ? "bg-bad text-white" : t.tone === "ok" ? "bg-ok text-white" : "bg-ink text-panel")}>
            {t.msg}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

// -- tooltip --------------------------------------------------------------------------------------

export function useTooltip() {
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null);
  const show = useCallback((e: { clientX: number; clientY: number }, text: string) => setTip({ x: e.clientX, y: e.clientY, text }), []);
  const hide = useCallback(() => setTip(null), []);
  const node = tip ? (
    <div className="tooltip" style={{ left: Math.min(tip.x + 12, window.innerWidth - 330), top: tip.y + 14 } as CSSProperties}>
      {tip.text}
    </div>
  ) : null;
  return { show, hide, node };
}
