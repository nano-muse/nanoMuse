/** What every page shares: the loading and failure states around a query, and a few
 *  small renderers used on several pages. */

import type { ReactNode } from "react";
import { errorText } from "../App";
import { dateOf, fmt, money, shortDay, siteDay } from "../lib/format";
import type { Query } from "../lib/hooks";
import { nameOf, useT } from "../lib/i18n";
import type { KindRow, ModelRow } from "../lib/types";
import { Ranks, modelColor } from "../ui/charts";
import { Failed, Loading, Panel } from "../ui/primitives";

export function Loaded<T>({ q, children, title }: { q: Query<T>; children: (data: T) => ReactNode; title?: ReactNode }) {
  if (q.data !== undefined) return <>{children(q.data)}</>;
  return (
    <Panel title={title}>
      {q.error ? <Failed error={errorText(q.error)} onRetry={() => void q.reload()} /> : <Loading />}
    </Panel>
  );
}

export const Updated = ({ at }: { at: number }) => {
  const T = useT();
  if (!at) return null;
  const d = new Date(at);
  return <span className="hint">{T.top.updated(`${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`)}</span>;
};

/** Day labels for a window of day starts. The stamps are site-local day starts:
 *  name them at the site's offset when the page knows it, the way the Usage page
 *  does, or an operator outside the site's timezone reads every bar as the day
 *  before. */
export const dayLabels = (days: number[], offsetH = 0): string[] =>
  days.map((d) => (offsetH ? siteDay(d, offsetH).slice(5) : shortDay(d)));
export const dayTitles = (days: number[], offsetH = 0): string[] =>
  days.map((d) => (offsetH ? siteDay(d, offsetH) : dateOf(d)));

export function KindRanks({ rows, metric = "cost" }: { rows: KindRow[]; metric?: "cost" | "requests" }) {
  const T = useT();
  return (
    <Ranks
      rows={rows.map((r, i) => ({
        name: nameOf(T.kinds, r.kind),
        value: metric === "cost" ? r.cost_cny : r.requests,
        sub: `${fmt(r.requests)} ${T.g.requests} · ${money(r.cost_cny)}`,
        color: `var(--c${(i % 8) + 1})`,
      }))}
      format={metric === "cost" ? (v) => money(v) : fmt}
      showShare
    />
  );
}

export function ModelRanks({ rows, metric = "cost", limit }: { rows: ModelRow[]; metric?: "cost" | "requests"; limit?: number }) {
  const T = useT();
  return (
    <Ranks
      rows={rows.map((r) => ({
        name: <code>{r.model}</code>,
        value: metric === "cost" ? r.cost_cny : r.requests,
        sub: `${fmt(r.requests)} ${T.g.requests} · ${fmt(r.prompt_tokens)} in · ${fmt(r.completion_tokens)} out · ${money(r.cost_cny)}`,
        color: modelColor(r.model),
      }))}
      format={metric === "cost" ? (v) => money(v) : fmt}
      showShare
      limit={limit}
    />
  );
}
