// The desktop's own log (src/main.ts, log). Every Host line lands in `<home>/desktop.log`
// — stdout and stderr alike — and the file was appended without ever being looked at
// again, so a long-lived install grew it without bound. The runtime's own log rotates at
// 10 MB (nanomuse/logger.py); the desktop log now steps aside at the same mark.
//
// Nothing here touches Electron, so `npm test` can run it over a fake home.

import { join } from "node:path";

/** The mark the runtime's own log rotates at; the desktop log steps aside at it too. */
export const LOG_ROTATE_BYTES = 10 * 1024 * 1024;

/** The file operations a rotation needs: injected so tests run without a real home. */
export interface RotateIO {
  /** The file's size in bytes, or undefined when there is no such file. */
  sizeOf(path: string): number | undefined;
  remove(path: string): void;
  rename(from: string, to: string): void;
}

/**
 * Steps `<dir>/desktop.log` aside as `desktop.log.1` (replacing the earlier one) once it
 * passes the cap, before the next line lands. Rotation trouble is swallowed — the line
 * still gets appended, and the next rotation bounds the file.
 */
export function rotateLogIfNeeded(dir: string, io: RotateIO): void {
  const logPath = join(dir, "desktop.log");
  const size = io.sizeOf(logPath);
  if (size === undefined || size < LOG_ROTATE_BYTES) {
    return;
  }
  const aside = `${logPath}.1`;
  try {
    io.remove(aside);
    io.rename(logPath, aside);
  } catch {
    /* the append still lands; a later line retries the rotation */
  }
}
