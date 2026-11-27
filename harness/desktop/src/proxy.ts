// The proxy for the model providers: one URL the person gives on the Cloud page's Network row,
// applied to the dsh Host *process* through its environment — Node's global fetch honours
// HTTP_PROXY / HTTPS_PROXY / NO_PROXY when NODE_USE_ENV_PROXY=1 (Node 24, which Electron 44
// carries; checked against a loopback forward proxy: an http:// and a socks5:// proxy are both
// taken, ALL_PROXY alone is not read). The bundled runtime for the hands, a child of the Host,
// inherits the same variables and httpx reads them too. nanoMuse Cloud and loopback are on
// NO_PROXY, so the relay, the hub's WebSocket and the sync never go through the proxy.

/** The schemes a proxy address may carry: a plain or TLS HTTP proxy, SOCKS5 with local or remote name lookup. */
export const PROXY_SCHEMES = ["http", "https", "socks5", "socks5h"] as const;

/** The relay every build knows (own-key installs read the star policy from it too). */
export const DEFAULT_RELAY_HOST = "cloud.nanomuse.cn";

/** Never through a proxy: the Host's own loopback, the operator's server, the connectors' callback. */
const LOOPBACK = ["localhost", "127.0.0.1", "::1"];

/**
 * The proxy address as it is kept, or undefined when `text` is not one: the scheme must be one
 * of PROXY_SCHEMES, a host is required, nothing else is checked. Trailing slashes go; the
 * scheme and host are lowercased by the URL parser; a `user:pass@` stays.
 */
export function validProxyUrl(text: string): string | undefined {
  const raw = text.trim();
  if (!raw) return undefined;
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return undefined;
  }
  const scheme = url.protocol.replace(/:$/, "");
  if (!(PROXY_SCHEMES as readonly string[]).includes(scheme) || !url.hostname) return undefined;
  if (url.search || url.hash || (url.pathname && url.pathname !== "/")) return undefined;
  return url.href.replace(/\/+$/, "");
}

/** The address for the screen: `user:pass@` becomes `•••@`, so a shared screenshot does not carry the password. */
export function maskProxyUrl(proxy: string): string {
  return proxy.replace(/^([a-z0-9+.-]+:\/\/)[^@/]+@/i, "$1•••@");
}

/** A URL's or a bare hostname's host, lowercased; empty when there is none. */
function hostOf(text: string): string {
  const s = text.trim().toLowerCase();
  if (!s) return "";
  try {
    return new URL(s.includes("://") ? s : `https://${s}`).hostname;
  } catch {
    return "";
  }
}

/**
 * The NO_PROXY list: loopback, the relay every build knows, and relay hosts from trusted
 * shell launch configuration, each once, in order.
 */
export function noProxyList(relayHosts: readonly string[]): string[] {
  const out = [...LOOPBACK, DEFAULT_RELAY_HOST];
  for (const entry of relayHosts) {
    const host = hostOf(entry);
    if (host && !out.includes(host)) out.push(host);
  }
  return out;
}

/** Relay exceptions come from the shell's trusted launch configuration, never renderer input. */
export function trustedRelayHosts(env: NodeJS.ProcessEnv = process.env): string[] {
  const configured = env.NANOMUSE_CLOUD_URL;
  return configured ? [configured] : [];
}

/**
 * What the Host's environment gets for `proxy`: nothing when it is empty or not an address;
 * otherwise HTTP_PROXY and HTTPS_PROXY (Node's fetch reads these for both schemes and for a
 * socks5 proxy too), ALL_PROXY for a SOCKS proxy (what httpx and curl read for one), NO_PROXY
 * with the relay and loopback, and NODE_USE_ENV_PROXY=1 so Node's fetch looks at them at all.
 */
export function proxyEnv(proxy: string | undefined, relayHosts: readonly string[] = []): Record<string, string> {
  const url = validProxyUrl(proxy ?? "");
  if (!url) return {};
  const env: Record<string, string> = { HTTP_PROXY: url, HTTPS_PROXY: url };
  if (url.startsWith("socks5")) env.ALL_PROXY = url;
  env.NO_PROXY = noProxyList(relayHosts).join(",");
  env.NODE_USE_ENV_PROXY = "1";
  return env;
}
