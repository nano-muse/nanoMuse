import { execFile } from "node:child_process";
import { mkdir, mkdtemp, rmdir } from "node:fs/promises";
import { join, win32 } from "node:path";

type ProbeStage = "create" | "label" | "cleanup";
export type TempProbe = { ok: true } | { ok: false; stage: ProbeStage; code: string; cleanupCode?: string };
type LabelDirectory = (directory: string) => Promise<void>;

function errorCode(error: unknown): string {
  const detail = error as { code?: string | number; signal?: string; killed?: boolean };
  return detail?.killed ? "timeout" : String(detail?.code ?? detail?.signal ?? "unknown");
}

/** Only the disposable probe gets a Low label, never its parent or any existing file. */
function labelDirectory(directory: string): Promise<void> {
  const command = join(process.env.SystemRoot ?? "C:\\Windows", "System32", "icacls.exe");
  return new Promise((resolve, reject) => {
    execFile(command, [directory, "/setintegritylevel", "(OI)(CI)L"], {
      windowsHide: true, timeout: 5_000, maxBuffer: 16_384,
    }, (error) => error ? reject(error) : resolve());
  });
}

/** DSH needs to label its fresh temp directory, even on a writable NTFS volume. */
export async function probeWindowsSandboxTemp(
  root: string,
  createRoot: boolean,
  label: LabelDirectory = labelDirectory,
): Promise<TempProbe> {
  let directory: string | undefined;
  let stage: ProbeStage = "create";
  let result: TempProbe = { ok: true };
  try {
    if (createRoot) await mkdir(root, { recursive: true });
    directory = await mkdtemp(join(root, "nanomuse-acl-probe-"));
    stage = "label";
    await label(directory);
  } catch (error) {
    result = { ok: false, stage, code: errorCode(error) };
  }
  if (directory) {
    try {
      await rmdir(directory);
    } catch (error) {
      const code = errorCode(error);
      result = result.ok ? { ok: false, stage: "cleanup", code } : { ...result, cleanupCode: code };
    }
  }
  return result;
}

interface TempOptions {
  platform: NodeJS.Platform;
  env: NodeJS.ProcessEnv;
  inheritedRoot: string;
  fallbackRoots: readonly string[];
  log: (line: string) => void;
  probe?: typeof probeWindowsSandboxTemp;
}

/** Choose only the host's environment. The Windows account's TEMP and TMP stay untouched. */
export async function windowsSandboxTempEnvironment(options: TempOptions): Promise<NodeJS.ProcessEnv> {
  const { platform, env, inheritedRoot, fallbackRoots, log, probe = probeWindowsSandboxTemp } = options;
  if (platform !== "win32") return env;
  const visited = new Set<string>();
  for (const [index, root] of [inheritedRoot, ...fallbackRoots].entries()) {
    // A relative TEMP would depend on the child's working directory and is not a stable root.
    if (!win32.isAbsolute(root)) {
      log(`sandbox TEMP: rejected ${JSON.stringify(root)} (path is not absolute)`);
      continue;
    }
    const identity = win32.normalize(root).replace(/[\\/]+$/, "").toLowerCase();
    if (visited.has(identity)) continue;
    visited.add(identity);
    const result = await probe(root, index > 0);
    if (!result.ok) {
      log(`sandbox TEMP: rejected ${JSON.stringify(root)} (stage=${result.stage}, code=${result.code}${result.cleanupCode ? `, cleanup=${result.cleanupCode}` : ""})`);
      continue;
    }
    if (index === 0) return env;
    const selected = { ...env };
    // Node chooses one case-insensitive key when spawning on Windows. Remove every spelling.
    for (const key of Object.keys(selected)) {
      if (["TEMP", "TMP", "TMPDIR"].includes(key.toUpperCase())) delete selected[key];
    }
    selected.TEMP = root;
    selected.TMP = root;
    selected.TMPDIR = root;
    log(`sandbox TEMP: using ${JSON.stringify(root)} for the host; Windows settings and sandbox policy are unchanged`);
    return selected;
  }
  log("sandbox TEMP: no usable directory; sandbox commands may remain blocked. Choose a writable Windows TEMP directory that accepts Low integrity labels, then fully quit and restart nanoMuse. Sandbox restrictions remain enabled.");
  return env;
}
