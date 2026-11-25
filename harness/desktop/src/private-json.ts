import {
  chmodSync,
  closeSync,
  existsSync,
  fsyncSync,
  mkdirSync,
  openSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { randomBytes } from "node:crypto";
import { dirname } from "node:path";

function syncDirectory(path: string): void {
  try {
    const fd = openSync(path, "r");
    try {
      fsyncSync(fd);
    } finally {
      closeSync(fd);
    }
  } catch {
    // Windows does not let Node fsync a directory.
  }
}

function privateTemp(path: string, contents: string): string {
  const tmp = `${path}.${process.pid}.${randomBytes(8).toString("hex")}.tmp`;
  let fd: number | undefined;
  try {
    fd = openSync(tmp, "wx", 0o600);
    writeFileSync(fd, contents, "utf8");
    fsyncSync(fd);
    closeSync(fd);
    fd = undefined;
    chmodSync(tmp, 0o600);
    return tmp;
  } catch (error) {
    if (fd !== undefined) closeSync(fd);
    rmSync(tmp, { force: true });
    throw error;
  }
}

/** Write private JSON beside its target, flush it, then atomically replace the target. */
export function writePrivateJson(path: string, value: unknown): void {
  const dir = dirname(path);
  const backup = `${path}.bak`;
  const json = JSON.stringify(value, null, 2);
  if (json === undefined) throw new TypeError("private JSON value is not serializable");
  mkdirSync(dir, { recursive: true });
  const tmp = privateTemp(path, `${json}\n`);
  try {
    if (existsSync(path)) {
      rmSync(backup, { force: true });
      renameSync(path, backup);
      chmodSync(backup, 0o600);
    }
    try {
      renameSync(tmp, path);
    } catch (error) {
      if (existsSync(backup) && !existsSync(path)) renameSync(backup, path);
      throw error;
    }
    chmodSync(path, 0o600);
    syncDirectory(dir);
  } finally {
    rmSync(tmp, { force: true });
  }
}

/**
 * Read JSON, falling back to the last complete replacement when the current
 * file is missing or damaged. A recovered target is private too.
 */
export function readPrivateJson<T>(path: string, accept: (value: unknown) => T | undefined): T | undefined {
  const parse = (candidate: string): { contents: string; value: T } | undefined => {
    try {
      const contents = readFileSync(candidate, "utf8");
      const value = accept(JSON.parse(contents) as unknown);
      return value === undefined ? undefined : { contents, value };
    } catch {
      return undefined;
    }
  };
  const current = parse(path);
  if (current !== undefined) {
    try {
      chmodSync(path, 0o600);
    } catch {
      // Reading an older read-only file is still better than losing its settings.
    }
    return current.value;
  }
  const backup = `${path}.bak`;
  const recovered = parse(backup);
  if (recovered === undefined) return undefined;
  try {
    chmodSync(backup, 0o600);
  } catch {
    // Recovery still uses the complete backup when an older read-only file cannot be tightened.
  }
  let tmp: string | undefined;
  try {
    mkdirSync(dirname(path), { recursive: true });
    const replacement = privateTemp(path, recovered.contents);
    tmp = replacement;
    try {
      renameSync(replacement, path);
      tmp = undefined;
    } catch {
      // Windows does not replace an existing file with rename. The backup remains intact
      // throughout, so an interruption after removing the damaged target is recoverable.
      rmSync(path, { force: true });
      renameSync(replacement, path);
      tmp = undefined;
    }
    chmodSync(path, 0o600);
    syncDirectory(dirname(path));
  } catch {
    // The complete backup is still usable for this launch.
  } finally {
    if (tmp) rmSync(tmp, { force: true });
  }
  return recovered.value;
}
