import type { MenuItemConstructorOptions, ContextMenuParams, WebContents } from "electron";
import { mediaPermissionAllowed, sameOrigin } from "./navigation";

/** Clipboard writes belong to the app's main page, never embedded content or workers. */
function clipboardWriteAllowed(permission: string, url: string | undefined, main: boolean, host: string | null): boolean {
  return permission === "clipboard-sanitized-write" && main && sameOrigin(url ?? "", host);
}

/** Install both permission paths; clipboard reads remain unavailable to page scripts. */
export function installWindowPermissions(contents: WebContents, hostUrl: () => string | null): void {
  contents.session.setPermissionRequestHandler((requester, permission, callback, details) => {
    const host = hostUrl();
    const media = details as Electron.MediaAccessPermissionRequest;
    callback(requester === contents && sameOrigin(contents.getURL(), host) && (
      clipboardWriteAllowed(permission, details.requestingUrl, details.isMainFrame, host) ||
      mediaPermissionAllowed(permission, details.requestingUrl, media.securityOrigin, media.mediaTypes, host)
    ));
  });
  contents.session.setPermissionCheckHandler((requester, permission, origin, details) => {
    const host = hostUrl();
    if (requester !== contents || !sameOrigin(contents.getURL(), host) || !sameOrigin(origin, host)) return false;
    if (clipboardWriteAllowed(permission, details.requestingUrl, details.isMainFrame, host)) return true;
    return mediaPermissionAllowed(permission, origin, details.embeddingOrigin, [details.mediaType ?? "unknown"], host) &&
      (!details.securityOrigin || sameOrigin(details.securityOrigin, host));
  });
}

/** Native editing acts on the person's selection and does not grant script clipboard reads. */
export function editContextMenu(params: Pick<ContextMenuParams, "isEditable" | "selectionText" | "editFlags">): MenuItemConstructorOptions[] {
  const { editFlags: flags } = params;
  if (params.isEditable) return [
    { role: "cut", enabled: flags.canCut },
    { role: "copy", enabled: flags.canCopy },
    { role: "paste", enabled: flags.canPaste },
    { type: "separator" },
    { role: "selectAll", enabled: flags.canSelectAll },
  ];
  return params.selectionText ? [{ role: "copy", enabled: flags.canCopy }] : [];
}
