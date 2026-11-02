import { join } from "node:path";
import { pathToFileURL } from "node:url";

/** Read Electron's executable path without starting the smoke test's Host. */
export async function electronPath(packageDir) {
  const { default: executable } = await import(pathToFileURL(join(packageDir, "index.js")).href);
  return executable;
}
