/**
 * Where the main window may go. It shows the Host's web app and nothing else from the
 * network: a navigation stays inside the Host's origin, or is one of the shell's own pages
 * from disk (the loading page); anything else is opened in the person's browser when it is
 * http(s), and dropped otherwise. Pure functions, so the tests can drive them without Electron.
 */

import { posix } from "node:path";

/** The only links that leave the app: http(s) with a host. */
export const EXTERNAL_URL = /^https?:\/\/[^/]/;

/**
 * Whether `url` is on `hostUrl`'s origin (scheme, host and port), compared as parsed URLs:
 * a prefix test let `http://127.0.0.1:38421@evil.example/` through, the Host's origin
 * standing as the user-info part of another host's address.
 */
export function sameOrigin(url: string, hostUrl: string | null): boolean {
  if (!hostUrl) return false;
  try {
    return new URL(url).origin === new URL(hostUrl).origin;
  } catch {
    return false;
  }
}

function normalizedFilePath(parsed: URL): string | null {
  if (parsed.protocol !== "file:") return null;
  let decoded: string;
  try {
    decoded = decodeURIComponent(parsed.pathname);
  } catch {
    return null;
  }
  if (decoded.includes("\0")) return null;
  // Normalize dot-segments after decoding percent-escapes and backslashes so a
  // `file:` URL carrying `..`, `%2e%2e`, `%2f` or `%5c` cannot escape ownResources.
  return posix.normalize(decoded.replace(/\\/g, "/"));
}

/** Whether `url` is one of the shell's own pages: a `file:` URL under `ownResources` (a directory path). */
export function ownPage(url: string, ownResourcesHref: string): boolean {
  let target: URL;
  let base: URL;
  try {
    target = new URL(url);
    base = new URL(ownResourcesHref);
  } catch {
    return false;
  }
  if (target.protocol !== "file:" || base.protocol !== "file:") return false;
  if (target.host.toLowerCase() !== base.host.toLowerCase()) return false;
  const targetPath = normalizedFilePath(target);
  const basePath = normalizedFilePath(base);
  if (!targetPath || !basePath) return false;
  const root = basePath.endsWith("/") ? basePath : `${basePath}/`;
  return targetPath.startsWith(root) && targetPath.length > root.length;
}

export type NavigationVerdict = "allow" | "external" | "deny";

/** What `will-navigate` does with `url`: let it through, hand it to the browser, or drop it. */
export function navigationVerdict(url: string, hostUrl: string | null, ownResourcesHref: string): NavigationVerdict {
  if (sameOrigin(url, hostUrl) || ownPage(url, ownResourcesHref)) return "allow";
  return EXTERNAL_URL.test(url) ? "external" : "deny";
}

/** Only same-origin, audio-only capture is available to the Host's dictation UI. */
export function mediaPermissionAllowed(
  permission: string,
  requestingUrl: string,
  embeddingOrigin: string | undefined,
  mediaTypes: readonly string[] | undefined,
  hostUrl: string | null,
): boolean {
  return (
    permission === "media" &&
    sameOrigin(requestingUrl, hostUrl) &&
    (!embeddingOrigin || sameOrigin(embeddingOrigin, hostUrl)) &&
    mediaTypes?.length === 1 &&
    mediaTypes[0] === "audio"
  );
}
