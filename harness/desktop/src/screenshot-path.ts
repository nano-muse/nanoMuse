import { existsSync } from "node:fs";
import { join } from "node:path";

/** The next free name for a report screenshot: two reports inside one second are two
 * files, as the browser's and the device screen's pictures already are. */
export function nextScreenshotPath(dir: string, stamp: string): string {
  let path = join(dir, `nanoMuse-${stamp}.png`);
  for (let n = 2; existsSync(path); n++) path = join(dir, `nanoMuse-${stamp}-${n}.png`);
  return path;
}
