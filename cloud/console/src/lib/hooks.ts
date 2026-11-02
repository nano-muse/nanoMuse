/** Data loading: one cache by URL for the session, stale answers shown while a fresh one is
 *  fetched, optional polling, and a bus so a change made in a drawer reloads the lists. */

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { ApiError, get } from "./api";
import { nowS } from "./format";

interface Entry {
  data: unknown;
  at: number;
  error: ApiError | null;
  promise: Promise<unknown> | null;
  /** Which fetch this entry belongs to; only the newest fetch's answer is written. */
  gen: number;
}

const CACHE = new Map<string, Entry>();
// Do not reuse a generation after signing out clears the cache.
let generation = 0;
const listeners = new Map<string, Set<() => void>>();

const notify = (url: string) => {
  for (const fn of listeners.get(url) || []) fn();
};

export function fetchInto(url: string, force = false): Promise<unknown> {
  const e = CACHE.get(url) || { data: undefined, at: 0, error: null, promise: null, gen: 0 };
  if (e.promise && !force) return e.promise;
  const mine = ++generation;
  const p = get(url)
    .then((d) => {
      const cur = CACHE.get(url);
      if (cur?.gen === mine) {
        CACHE.set(url, { data: d, at: Date.now(), error: null, promise: null, gen: mine });
        notify(url);
      }
      return d;
    })
    .catch((err: ApiError) => {
      const cur = CACHE.get(url);
      if (cur?.gen === mine) {
        CACHE.set(url, { data: cur.data, at: cur.at, error: err, promise: null, gen: mine });
        notify(url);
      }
      throw err;
    });
  CACHE.set(url, { ...e, promise: p, gen: mine });
  notify(url);
  return p;
}

/** Drop every cached answer whose URL starts with one of the prefixes (after an action). */
export function invalidate(...prefixes: string[]): void {
  for (const url of Array.from(CACHE.keys())) {
    if (prefixes.some((p) => url.startsWith(p))) {
      const e = CACHE.get(url)!;
      CACHE.set(url, { ...e, at: 0 });
      void fetchInto(url, true).catch(() => undefined);
    }
  }
}

export function clearCache(): void {
  CACHE.clear();
}

/** The cache's current answer for a URL — the tests' window into the session cache. */
export function cachedAnswer(url: string): { data: unknown; at: number; error: ApiError | null } | undefined {
  const e = CACHE.get(url);
  return e ? { data: e.data, at: e.at, error: e.error } : undefined;
}

export interface Query<T> {
  data: T | undefined;
  error: ApiError | null;
  loading: boolean;
  at: number;
  reload: () => Promise<void>;
}

/** `url` null means not now. `poll` in ms refetches while the tab is visible. `maxAge` in ms:
 *  a cached answer younger than this is not refetched on mount. */
export function useData<T>(url: string | null, opts: { poll?: number; maxAge?: number } = {}): Query<T> {
  const { poll = 0, maxAge = 15_000 } = opts;
  const subscribe = useCallback(
    (fn: () => void) => {
      if (!url) return () => undefined;
      let set = listeners.get(url);
      if (!set) listeners.set(url, (set = new Set()));
      set.add(fn);
      return () => {
        set!.delete(fn);
      };
    },
    [url],
  );
  const snap = useSyncExternalStore(subscribe, () => (url ? CACHE.get(url) || null : null));
  const reload = useCallback(async () => {
    if (!url) return;
    await fetchInto(url, true).catch(() => undefined);
  }, [url]);
  useEffect(() => {
    if (!url) return;
    const e = CACHE.get(url);
    if (!e || !e.promise) {
      if (!e || Date.now() - e.at > maxAge) void fetchInto(url).catch(() => undefined);
    }
    if (!poll) return;
    const tick = () => {
      if (document.visibilityState === "visible") void fetchInto(url).catch(() => undefined);
    };
    const id = setInterval(tick, poll);
    document.addEventListener("visibilitychange", tick);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [url, poll, maxAge]);
  return {
    data: snap?.data as T | undefined,
    error: snap?.error || null,
    loading: !!snap?.promise && snap.data === undefined,
    at: snap?.at || 0,
    reload,
  };
}

/** What a stored raw string reads back as: a value another page (or another era of this
 * one) wrote. A number that no longer parses — "abc", an empty string — falls back to
 * the initial value instead of arriving as NaN or 0. */
export function storedValue<T extends string | number | boolean>(raw: string | null, initial: T): T {
  if (raw === null) return initial;
  if (typeof initial === "number") {
    const n = Number(raw);
    return (raw.trim() !== "" && Number.isFinite(n) ? n : initial) as T;
  }
  if (typeof initial === "boolean") return (raw === "1") as T;
  return raw as T;
}

/** A value kept in localStorage. */
export function useStored<T extends string | number | boolean>(key: string, initial: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => storedValue(localStorage.getItem(key), initial));
  const set = useCallback(
    (x: T) => {
      setV(x);
      localStorage.setItem(key, typeof x === "boolean" ? (x ? "1" : "0") : String(x));
    },
    [key],
  );
  return [v, set];
}

/** A ticking clock for the "x s ago" labels on the live page. */
/** The clock, in seconds, re-read every `ms`: for ages and drifts drawn during render. */
export function useNow(ms = 30_000): number {
  const [t, setT] = useState(nowS);
  useEffect(() => {
    const id = setInterval(() => setT(nowS()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return t;
}

export function useTick(ms: number): number {
  const [n, setN] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setN((x) => x + 1), ms);
    return () => clearInterval(id);
  }, [ms]);
  return n;
}

export function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}

/** Run an action with a busy flag and an error message; the toast is the page's. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>("");
  const alive = useRef(true);
  useEffect(
    () => () => {
      alive.current = false;
    },
    [],
  );
  const run = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true);
    setError("");
    try {
      return await fn();
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : String(e));
      return undefined;
    } finally {
      if (alive.current) setBusy(false);
    }
  }, []);
  return { busy, error, run, setError };
}
