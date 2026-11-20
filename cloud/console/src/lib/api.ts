/** The relay's admin API: one token in sessionStorage, X-Admin-Actor for the audit log,
 *  a 401 that locks the console, and the `places` ({ip: place}) every answer may carry,
 *  kept across answers so an address is named wherever it appears. */

import { mergePlaces } from "./places";

const KEY = "nm.admin";
const ACTOR_KEY = "nm.admin.actor";

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

let authRevision = Symbol();
let onLocked: (() => void) | null = null;
export const setLockedHandler = (fn: () => void) => {
  onLocked = fn;
};

export const token = {
  get: () => sessionStorage.getItem(KEY) || "",
  set: (t: string) => { sessionStorage.setItem(KEY, t); authRevision = Symbol(); },
  clear: () => { sessionStorage.removeItem(KEY); authRevision = Symbol(); },
};

export const actor = {
  get: () => sessionStorage.getItem(ACTOR_KEY) || "",
  set: (name: string) => sessionStorage.setItem(ACTOR_KEY, name.trim()),
};

export function headers(json = false): Record<string, string> {
  const h: Record<string, string> = { "X-Admin-Token": token.get() };
  if (actor.get()) h["X-Admin-Actor"] = actor.get();
  if (json) h["Content-Type"] = "application/json";
  return h;
}

/** An old request may finish after a new sign-in, even one using the same token. */
function lockRejectedToken(rejected: string, revision: symbol): void {
  if (authRevision !== revision || token.get() !== rejected) return;
  token.clear();
  onLocked?.();
}

export async function api<T = unknown>(method: string, path: string, body?: unknown, adminToken?: string): Promise<T> {
  const sentHeaders = headers(body !== undefined);
  const sentRevision = authRevision;
  if (adminToken !== undefined) sentHeaders["X-Admin-Token"] = adminToken;
  let r: Response;
  try {
    r = await fetch(path, { method, headers: sentHeaders, body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store" });
  } catch {
    throw new ApiError(0, "offline", "offline");
  }
  if (r.status === 401) {
    lockRejectedToken(sentHeaders["X-Admin-Token"], sentRevision);
    throw new ApiError(401, "admin", "admin");
  }
  if (r.status === 204) return null as T;
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    const e = (j && j.error) || {};
    throw new ApiError(r.status, e.code || `http_${r.status}`, e.message || r.statusText || `HTTP ${r.status}`);
  }
  mergePlaces(j);
  return j as T;
}

export const get = <T = unknown>(path: string, adminToken?: string) => api<T>("GET", path, undefined, adminToken);
export const post = <T = unknown>(path: string, body?: unknown) => api<T>("POST", path, body ?? {});
export const put = <T = unknown>(path: string, body?: unknown) => api<T>("PUT", path, body ?? {});
export const del = <T = unknown>(path: string) => api<T>("DELETE", path);

/** A file from the relay (CSV, JSONL): fetched with the token, since a bare link could not carry it. */
export async function download(path: string, name: string, bom = false): Promise<void> {
  const sentHeaders = headers();
  const sentRevision = authRevision;
  const r = await fetch(path, { headers: sentHeaders, cache: "no-store" });
  if (r.status === 401) {
    lockRejectedToken(sentHeaders["X-Admin-Token"], sentRevision);
    throw new ApiError(401, "admin", "admin");
  }
  if (!r.ok) throw new ApiError(r.status, `http_${r.status}`, `HTTP ${r.status}${r.statusText ? " " + r.statusText : ""}`);
  const blob = await r.blob();
  if (!blob.size) throw new ApiError(0, "empty", "empty");
  saveBlob(bom ? new Blob(["\ufeff", blob]) : blob, name);
}

export function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export const qs = (params: Record<string, string | number | boolean | undefined | null>): string => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "" && v !== false) p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
};
