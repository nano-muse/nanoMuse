// Staging under a path with spaces (scripts/prepare-dsh.mjs): on Windows npm and pnpm
// are .cmd shims, and a .cmd child can only be started through the shell. cmd.exe splits
// an unquoted argument at its spaces, so `pnpm pack --pack-destination <a path with
// spaces>` reached pnpm as two arguments and staging failed with "pnpm pack left no
// tarball". The script's child arguments are quoted for the shell (scripts/shell-args.mjs);
// this pins the decision, the real round trip through cmd.exe, and that run() uses it.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { shellArgs } from "../scripts/shell-args.mjs";

test("an argument with spaces is quoted, a plain one is passed as it is", () => {
  assert.deepEqual(
    shellArgs(["pack", "--pack-destination", "C:\\Users\\John Doe\\AppData\\Local\\Temp\\nanomuse-bundle-1"]),
    ["pack", "--pack-destination", '"C:\\Users\\John Doe\\AppData\\Local\\Temp\\nanomuse-bundle-1"'],
  );
  assert.deepEqual(shellArgs(["install", "--registry=https://registry.npmjs.org"]), [
    "install",
    "--registry=https://registry.npmjs.org",
  ]);
});

test("through the shell a quoted argument with spaces arrives as one argument", { skip: process.platform !== "win32" }, () => {
  // a batch file that reports how cmd.exe split its arguments: %1 and %2 as cmd sees them
  const dir = mkdtempSync(join(tmpdir(), "nanomuse-shell-args-"));
  try {
    const echo = join(dir, "echo-args.cmd");
    writeFileSync(echo, "@echo off\r\necho [%1][%2]\r\n");
    const withSpace = join(dir, "two words.txt");
    const quoted = execFileSync(echo, shellArgs([withSpace, "plain"]), {
      shell: true,
      encoding: "utf8",
    }).trim();
    // one argument, spaces and all, then the second one
    assert.equal(quoted, `["${withSpace}"][plain]`);
    // without the quoting the same path is split at its spaces and never arrives whole
    const split = execFileSync(echo, [withSpace, "plain"], {
      shell: true,
      encoding: "utf8",
    }).trim();
    assert.notEqual(split, quoted);
    assert.ok(!split.includes(withSpace), `cmd.exe delivered the path whole anyway: ${split}`);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("prepare-dsh runs its children with shell-quoted arguments", () => {
  const script = readFileSync(new URL("../scripts/prepare-dsh.mjs", import.meta.url), "utf8");
  assert.match(script, /import \{ shellArgs \} from "\.\/shell-args\.mjs";/);
  assert.match(script, /const argv = shell \? shellArgs\(cmdArgs\) : cmdArgs;/);
  // the shell itself is only on where the .cmd shims need it
  assert.match(script, /const shell = process\.platform === "win32";/);
});
