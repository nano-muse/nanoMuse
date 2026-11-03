/** The client behind a user agent, the way the relay's client.py reads it, for the rows
 *  that carry a raw user agent (sessions, the showcase's visitors). */

const APP_TOKENS: [string, string][] = [
  ["nanoMuse-Android", "android"],
  ["nanoMuse-iOS", "ios"],
  ["nanoMuse-Desktop", "desktop"],
  ["deepseek-harness", "desktop"],
  // the Python runtime of 1.0.6 and earlier signed its model calls with the OpenAI SDK's
  // own string; the relay's client.py reads it, and so does this mirror of it
  ["AsyncOpenAI/Python", "runtime"],
  ["Minis/", "minis"],
];
const SYSTEMS: [string, string][] = [
  ["ios", "ios"],
  ["iphone", "ios"],
  ["ipad", "ios"],
  ["android", "android"],
  ["windows", "windows"],
  ["darwin", "macos"],
  ["macos", "macos"],
  ["mac os", "macos"],
  ["linux", "linux"],
];

export const PLATFORMS = ["android", "ios", "desktop", "windows", "macos", "linux", "runtime", "browser", "minis", "other"] as const;

export function platformOf(ua: string | null | undefined): string {
  const s = String(ua || "");
  for (const [tok, p] of APP_TOKENS) if (s.startsWith(tok)) return p;
  if (s.startsWith("nanoMuse/")) {
    const a = s.indexOf("("),
      b = s.indexOf(")");
    const system = a >= 0 && b > a ? s.slice(a + 1, b).toLowerCase() : "";
    for (const [mark, p] of SYSTEMS) if (system.startsWith(mark)) return p;
    return "runtime";
  }
  if (s.startsWith("Mozilla/")) return "browser";
  return "other";
}

export const isApp = (platform: string) => platform !== "other";

export function clientVersion(ua: string | null | undefined): string {
  const head = String(ua || "").split(" ", 1)[0];
  if (head.includes("/") && head.startsWith("nanoMuse")) return head.split("/", 2)[1].slice(0, 24);
  return "";
}

export function uaFamily(ua: string | null | undefined): string {
  const s = String(ua || "").trim();
  if (!s) return "(empty)";
  const head = s.split(" ", 1)[0];
  if (head.startsWith("Mozilla/")) return "Mozilla";
  return head.split("/", 1)[0].slice(0, 40) || "(empty)";
}

export function browserOf(ua: string | null | undefined): string {
  const s = String(ua || "");
  const os = /Android/.test(s) ? "Android" : /iPhone|iPad/.test(s) ? "iOS" : /Windows/.test(s) ? "Windows" : /Mac OS/.test(s) ? "macOS" : /Linux/.test(s) ? "Linux" : "";
  const b = /Edg\//.test(s) ? "Edge" : /OPR\//.test(s) ? "Opera" : /Chrome\//.test(s) ? "Chrome" : /Firefox\//.test(s) ? "Firefox" : /Safari\//.test(s) ? "Safari" : "";
  return [os, b].filter(Boolean).join(" ") || s.split(" ")[0];
}

/** One short line for a user agent: the app and version, or the browser. */
export function clientLine(ua: string | null | undefined): string {
  const p = platformOf(ua);
  if (p === "browser") return browserOf(ua);
  const v = clientVersion(ua);
  return v ? `${p} ${v}` : p === "other" ? uaFamily(ua) : p;
}
