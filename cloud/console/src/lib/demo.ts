/** The demo page's per-day visit bars: bucket the active and recent-visit lists by
 *  site-local day. */
import type { DemoVisit } from "./types";

export function perDayVisits(
  active: DemoVisit[] | undefined,
  visits: DemoVisit[] | undefined,
  days: number,
  offsetH: number,
  now: number,
): { per: number[]; start: number } {
  const dayStart = now - ((now + offsetH * 3600) % 86400);
  const n = Math.min(days, 90);
  const start = dayStart - (n - 1) * 86400;
  const per = new Array(n).fill(0);
  // a visit still running sits in the active list and the recent list both; the
  // page's own table counts it once, and so must the chart
  const seen = new Set((active || []).map((a) => a.id));
  const all = [...(active || []), ...(visits || []).filter((v) => !seen.has(v.id))];
  for (const v of all) if (v.started >= start) per[Math.min(n - 1, Math.floor((v.started - start) / 86400))]++;
  return { per, start };
}
