/**
 * The hosted showcase.
 *
 * On the public site this simulator is served next to a *showcase gateway* (`demo/showcase/`
 * in the nanoMuse repository). Ask it for a session and it starts a private nanoMuse for this
 * visitor — its own container, its own token, GUI operation on — for a limited time and within
 * a model budget. Visitors may also bring their own model key; it goes to the gateway and stays
 * there, the container never sees it.
 *
 * `VITE_NANOMUSE_DEMO` at build time (e.g. `/api/demo`) is what turns this on; a normal
 * MobileGym checkout has it empty and the app asks for a server address instead.
 */

export interface DemoInfo {
  session_ttl_s: number;
  demo_model: string | null;
  byok: boolean;
  byok_hosts: string[];
  /** The showcase wants a nanoMuse Cloud sign-in before it starts a Muse (visitors.py). */
  signin_required?: boolean;
  quota: { requests: number; tokens: number };
  active_sessions: number;
  max_sessions: number;
}

/** Who signed in, as the relay masks it — `195****0404`, `g…@gmail.com`; never the identifier. */
export interface DemoVisitor {
  hint: string;
  channel: string;
  created: boolean;
}

export interface DemoProvider {
  base_url: string;
  api_key: string;
  model: string;
}

export interface DemoSession {
  id: string;
  serverUrl: string;
  token: string;
  /** Unix seconds. */
  expiresAt: number;
  byok: boolean;
}

export class DemoError extends Error {
  constructor(
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(gateway: string, path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${gateway.replace(/\/+$/, '')}${path}`, init);
  } catch {
    throw new DemoError('unreachable', 'The showcase server cannot be reached.');
  }
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    // not JSON
  }
  if (!res.ok) {
    const err = (data ?? {}) as { error?: string; message?: string; detail?: unknown };
    throw new DemoError(err.error ?? String(res.status), err.message ?? `The showcase server answered ${res.status}.`);
  }
  return data as T;
}

export function fetchDemoInfo(gateway: string): Promise<DemoInfo> {
  return call<DemoInfo>(gateway, '/info');
}

/** A code to the phone or the inbox, through the gateway to nanoMuse Cloud. */
export function requestSignInCode(gateway: string, identifier: string): Promise<void> {
  return call<void>(gateway, '/signin/code', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ identifier }),
  });
}

/** The code back → a ticket this browser keeps, and who it is. */
export function verifySignInCode(
  gateway: string,
  identifier: string,
  code: string,
): Promise<{ ticket: string; visitor: DemoVisitor }> {
  return call(gateway, '/signin/verify', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ identifier, code }),
  });
}

/** The password way in, for accounts that set one under Account. */
export function signInWithPassword(
  gateway: string,
  identifier: string,
  password: string,
): Promise<{ ticket: string; visitor: DemoVisitor }> {
  return call(gateway, '/signin/login', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ identifier, password }),
  });
}

/** Hands the ticket back; the next demo asks for a sign-in again. */
export async function signOut(gateway: string, ticket: string): Promise<void> {
  try {
    await call<void>(gateway, '/signout', { method: 'POST', headers: { authorization: `Bearer ${ticket}` } });
  } catch {
    // the ticket lapses by itself in any case
  }
}

export async function startDemoSession(
  gateway: string,
  provider?: DemoProvider,
  ticket?: string,
): Promise<DemoSession> {
  const headers: Record<string, string> = { 'content-type': 'application/json' };
  if (ticket) headers.authorization = `Bearer ${ticket}`;
  // the visitor's time zone goes with the request: the Muse's clock (what "in 2 minutes"
  // and "at 17:58" mean in its replies and reminders) is then the visitor's, not the server's
  const body: { provider?: DemoProvider; time_zone?: string } = provider ? { provider } : {};
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (zone) body.time_zone = zone;
  } catch {
    // no Intl, or no zone to tell: the Muse keeps the server's clock
  }
  const raw = await call<{ id: string; server_url: string; token: string; expires_at: number; byok: boolean }>(
    gateway,
    '/session',
    {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    },
  );
  return { id: raw.id, serverUrl: raw.server_url, token: raw.token, expiresAt: raw.expires_at, byok: raw.byok };
}

/** The reply language the runtime understands (its *Settings › Reply language* values). */
export type ReplyLanguage = 'English' | '中文';

/**
 * The hosted Muse answers in the language of the page it sits in: the showcase sets the
 * runtime's reply language (what *Settings › Reply language* does) from the visitor's choice,
 * so a Chinese chat read on an English page is reported in English, and the capsule's
 * sentences follow. The fresh container may still be coming up: tried for a while.
 */
export async function setReplyLanguage(serverUrl: string, token: string, language: ReplyLanguage): Promise<boolean> {
  for (let attempt = 0; attempt < 15; attempt++) {
    try {
      const res = await fetch(`${serverUrl}/api/settings`, {
        method: 'PUT',
        headers: { 'content-type': 'application/json', authorization: `Bearer ${token}` },
        body: JSON.stringify({ language }),
      });
      if (res.ok) return true;
      if (res.status === 401 || res.status === 403 || res.status === 404) return false;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  return false;
}

export async function endDemoSession(gateway: string, id: string, token: string): Promise<void> {
  try {
    await call<void>(gateway, `/session/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      headers: { authorization: `Bearer ${token}` },
    });
  } catch {
    // already gone, or unreachable: either way it is over for us
  }
}
