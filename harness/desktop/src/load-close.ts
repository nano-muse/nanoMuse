// A closed window can reject its pending Host load. Suppress that failure only when
// the window is gone. ERR_ABORTED alone also means a live window started another
// navigation, so it must not turn an unsuccessful startup into apparent success.

/** The part of a BrowserWindow the classification needs. */
export interface LoadWindow {
  isDestroyed(): boolean;
}

/** Whether the window has gone away while loading the Host. */
export function closedDuringLoad(win: LoadWindow): boolean {
  return win.isDestroyed();
}
