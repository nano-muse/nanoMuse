// A loadURL rejection is not always a failure (src/main.ts, loadHost). The window the
// Host's page was loading into can be closed mid-load — the person changed their mind, or
// the app is quitting — and Electron rejects the pending load with ERR_ABORTED or, once
// the window is gone, "Object has been destroyed". That is not a start failure to report:
// before this, closing the window during the load failed the whole boot, showed the
// "could not start" dialog and quit the app on a person who had only closed a window.
//
// Nothing here touches Electron, so `npm test` can classify rejections with fakes.

/** The part of a BrowserWindow the classification needs. */
export interface LoadWindow {
  isDestroyed(): boolean;
}

/** True when a loadURL rejection is only the window going away — the load was cancelled by
 *  the close, not failed by the host. */
export function closedDuringLoad(win: LoadWindow, exc: unknown): boolean {
  return win.isDestroyed() || (exc as { code?: string } | null)?.code === "ERR_ABORTED";
}
