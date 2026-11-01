/** Numbers, money, dates and durations as the console prints them. */

export const nowS = () => Math.floor(Date.now() / 1000);

export const fmt = (n: number | null | undefined): string => (n === null || n === undefined || Number.isNaN(Number(n)) ? "0" : Math.round(Number(n)).toLocaleString("en-US"));

/** 12.3k, 1.2M for a tight cell. */
export const compact = (n: number | null | undefined): string => {
  const v = Number(n || 0);
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(a >= 1e10 ? 0 : 1)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(a >= 1e7 ? 0 : 1)}M`;
  if (a >= 1e4) return `${(v / 1e3).toFixed(0)}k`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(1)}k`;
  return fmt(v);
};

export const money = (cny: number | null | undefined, digits = 2): string => {
  const v = Number(cny || 0);
  if (v !== 0 && Math.abs(v) < 0.01 && digits <= 2) return `¥${v.toFixed(4)}`;
  return `¥${v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
};
export const moneyN = (cny: number | null | undefined): string => Number(cny || 0).toFixed(4).replace(/\.?0+$/, "") || "0";
export const usd = (cny: number | null | undefined, rate: number): string => (rate > 0 ? `$${(Number(cny || 0) / rate).toFixed(2)}` : "");

export const pct = (x: number | null | undefined, digits = 0): string => `${(Number(x || 0) * 100).toFixed(digits)}%`;

export const ms = (v: number | null | undefined): string => {
  const n = Number(v || 0);
  if (n >= 10_000) return `${(n / 1000).toFixed(1)} s`;
  if (n >= 1000) return `${(n / 1000).toFixed(2)} s`;
  return `${Math.round(n)} ms`;
};

export const bytes = (n: number | null | undefined): string => {
  const v = Number(n || 0);
  if (v >= 1 << 30) return `${(v / (1 << 30)).toFixed(2)} GB`;
  if (v >= 1 << 20) return `${(v / (1 << 20)).toFixed(1)} MB`;
  if (v >= 1024) return `${(v / 1024).toFixed(0)} KB`;
  return `${v} B`;
};

export const dur = (s: number, zh: boolean): string => {
  if (s < 60) return zh ? `${Math.round(s)} 秒` : `${Math.round(s)} s`;
  if (s < 3600) return zh ? `${Math.round(s / 60)} 分钟` : `${Math.round(s / 60)} min`;
  if (s < 86400) return zh ? `${(s / 3600).toFixed(1)} 小时` : `${(s / 3600).toFixed(1)} h`;
  return zh ? `${(s / 86400).toFixed(1)} 天` : `${(s / 86400).toFixed(1)} d`;
};

export const ago = (ts: number | null | undefined, zh: boolean): string => {
  if (!ts) return zh ? "从未" : "never";
  const d = nowS() - Number(ts);
  if (d < 60) return zh ? "刚刚" : "just now";
  if (d < 3600) return zh ? `${Math.floor(d / 60)} 分钟前` : `${Math.floor(d / 60)} min ago`;
  if (d < 86400) return zh ? `${Math.floor(d / 3600)} 小时前` : `${Math.floor(d / 3600)} h ago`;
  if (d < 30 * 86400) return zh ? `${Math.floor(d / 86400)} 天前` : `${Math.floor(d / 86400)} d ago`;
  return dateOf(ts);
};

const pad = (n: number) => String(n).padStart(2, "0");
export const dateOf = (ts: number | null | undefined): string => {
  if (!ts) return "";
  const d = new Date(Number(ts) * 1000);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};
export const when = (ts: number | null | undefined): string => {
  if (!ts) return "";
  const d = new Date(Number(ts) * 1000);
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
export const clock = (ts: number | null | undefined, seconds = false): string => {
  if (!ts) return "";
  const d = new Date(Number(ts) * 1000);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}${seconds ? ":" + pad(d.getSeconds()) : ""}`;
};
export const iso = (ts: number | null | undefined): string => (ts ? new Date(Number(ts) * 1000).toISOString() : "");
/** "10-24" for a day's start (a UNIX time, local day). */
export const shortDay = (ts: number): string => {
  const d = new Date(ts * 1000);
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};
export const dayUtc = (ts: number): string => new Date(ts * 1000).toISOString().slice(0, 10);
const weekdayName = (i: number, zh: boolean): string =>
  (zh ? ["日", "一", "二", "三", "四", "五", "六"] : ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"])[i];
export const weekday = (ts: number, zh: boolean): string => weekdayName(new Date(ts * 1000).getDay(), zh);
/** The relay's day stamp is the site-local day's start as a UNIX time: the date it names
 *  is the calendar date at the site's day offset, not whatever the operator's browser
 *  happens to run in. */
export const siteDay = (day: number, offsetH: number): string => dayUtc(day + offsetH * 3600);
/** The start of the site-local day `t` falls in, as a UNIX time. */
export const siteDayStart = (t: number, offsetH: number): number => t - ((t + offsetH * 3600) % 86400);
export const siteWeekday = (day: number, offsetH: number, zh: boolean): string =>
  weekdayName(new Date((day + offsetH * 3600) * 1000).getUTCDay(), zh);
/** The day stamp a picked calendar date names at the site's offset. */
export const siteDayStamp = (iso: string, offsetH: number): number => {
  const [y, m, d] = iso.split("-").map(Number);
  return Math.floor(Date.UTC(y, m - 1, d) / 1000) - offsetH * 3600;
};

export const sum = <T,>(rows: T[], key: (r: T) => number): number => rows.reduce((a, r) => a + (Number(key(r)) || 0), 0);
export const maxOf = (xs: number[]): number => xs.reduce((a, b) => (b > a ? b : a), 0);

/** Every word of `q`, anywhere in `text`, all of them. */
export const terms = (q: string | null | undefined): string[] =>
  String(q || "")
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean);
export const matches = (text: string, ts: string[]): boolean => ts.every((t) => text.includes(t));

export const csvEscape = (v: unknown): string => {
  const s = v === null || v === undefined ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};
export const toCsv = (cols: string[], rows: unknown[][]): string => [cols.join(","), ...rows.map((r) => r.map(csvEscape).join(","))].join("\n");
