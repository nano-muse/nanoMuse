#!/usr/bin/env node
// Stage the harness the desktop app carries: `dsh/` next to this file's parent, with
// `@deepseek-ai/dsh` (the version the bundle's peer dependencies name) and the nanoMuse
// bundle installed side by side by npm — the Loader finds a bundle linked from the profile
// to that copy, so no pnpm runs on the person's machine.
//
//   node scripts/prepare-dsh.mjs                      # packs ../dsh-nanomuse (built first: pnpm build)
//   node scripts/prepare-dsh.mjs --bundle path.tgz    # a tarball already packed (the CI's)
//   node scripts/prepare-dsh.mjs --out dsh            # where to stage (default: ./dsh)
//
// Run on the platform being packaged: npm picks that platform's native prebuilds
// (node-pty, sharp, koffi, the harness's own require-builtin addon); on Linux sharp's
// native build is then swapped for its WebAssembly one (see "sharp on Linux" below). Only
// the public registry is used, whatever ~/.npmrc says.

import { execFileSync } from "node:child_process";
import { chmodSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const appDir = resolve(here, "..");
const bundleDir = resolve(appDir, "..", "dsh-nanomuse");
const REGISTRY = "https://registry.npmjs.org";

const args = process.argv.slice(2);
const opt = (name) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : undefined;
};
const out = resolve(appDir, opt("--out") ?? "dsh");
let bundle = opt("--bundle");

const run = (cmd, cmdArgs, options = {}) => {
  console.log("+", cmd, cmdArgs.join(" "));
  return execFileSync(cmd, cmdArgs, { stdio: "inherit", ...options });
};
const npm = process.platform === "win32" ? "npm.cmd" : "npm";
const pnpm = process.platform === "win32" ? "pnpm.cmd" : "pnpm";
const shell = process.platform === "win32";

// ---------------------------------------------------------------- the versions
const bundleManifest = JSON.parse(readFileSync(join(bundleDir, "package.json"), "utf8"));
const dshVersion = bundleManifest.peerDependencies?.["@deepseek-ai/dsh-agent"];
if (!dshVersion) throw new Error("dsh-nanomuse/package.json names no @deepseek-ai/dsh-agent peer — which dsh is this for?");
console.log(`dsh ${dshVersion} · ${bundleManifest.name} ${bundleManifest.version}`);

// ---------------------------------------------------------------- the bundle
if (!bundle) {
  if (!existsSync(join(bundleDir, "lib", "index.js"))) {
    throw new Error(`${bundleDir}/lib is missing — run 'pnpm install && pnpm build' there first`);
  }
  const packDir = join(tmpdir(), `nanomuse-bundle-${process.pid}`);
  mkdirSync(packDir, { recursive: true });
  run(pnpm, ["pack", "--pack-destination", packDir], { cwd: bundleDir, shell });
  const tgz = readdirSync(packDir).find((f) => f.endsWith(".tgz"));
  if (!tgz) throw new Error("pnpm pack left no tarball");
  bundle = join(packDir, tgz);
}
bundle = resolve(bundle);
if (!existsSync(bundle)) throw new Error(`no bundle at ${bundle}`);

// ---------------------------------------------------------------- the install
rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });
writeFileSync(
  join(out, "package.json"),
  `${JSON.stringify({ name: "nanomuse-desktop-dsh", private: true, description: "DeepSeek Harness and the nanoMuse bundle, as nanoMuse Desktop carries them" }, null, 2)}\n`,
);
// No install scripts, whatever the npm version's policy (npm 11 blocks them by default,
// npm 10 runs them): the harness's dependencies carry prebuilt binaries and their scripts
// only check for them — except one, which the step after this one does by hand.
run(
  npm,
  ["install", "--omit=dev", "--no-audit", "--no-fund", "--no-package-lock", "--ignore-scripts", `--registry=${REGISTRY}`, `@deepseek-ai/dsh@${dshVersion}`, bundle],
  { cwd: out, shell, env: { ...process.env, npm_config_registry: REGISTRY } },
);
// what @deepseek-ai/dsh-subprocess-local's postinstall does: the executable bit the tarball
// stripped from node-pty's prebuilt spawn-helper (macOS and Linux)
if (process.platform !== "win32") {
  for (const helper of [
    join(out, "node_modules", "node-pty", "prebuilds", `${process.platform}-${process.arch}`, "spawn-helper"),
    join(out, "node_modules", "node-pty", "build", "Release", "spawn-helper"),
  ]) {
    if (existsSync(helper)) chmodSync(helper, 0o755);
  }
}

// ---------------------------------------------------------------- sharp on Linux
// The Host runs inside the Electron binary (ELECTRON_RUN_AS_NODE), and Electron's Linux
// build links the system's GLib and leaks its symbols into the process; sharp's prebuilt
// libvips carries a GLib of its own, and the two meet in one process (electron/electron#46323;
// sharp's install notes, "Electron and Linux"). On most systems that is a GLib-GObject-CRITICAL
// line for every picture; on some it is a SIGSEGV on the first decode, which kills the Host
// mid-turn (#274). So the Linux package carries sharp's WebAssembly build and not the native
// one: sharp's loader falls through to @img/sharp-wasm32 when the platform's prebuild is
// absent, and the wasm build has no GLib to clash with. About twice the time per picture
// (50 ms for a 2560x1440 screenshot against 22 ms), half the size on disk.
const imgDir = join(out, "node_modules", "@img");
if (process.platform === "linux") {
  const sharpVersion = JSON.parse(readFileSync(join(out, "node_modules", "sharp", "package.json"), "utf8")).version;
  const wasm = join(imgDir, "sharp-wasm32");
  const wasmVersion = existsSync(wasm) ? JSON.parse(readFileSync(join(wasm, "package.json"), "utf8")).version : null;
  if (wasmVersion !== sharpVersion) {
    run(
      npm,
      ["install", "--omit=dev", "--no-audit", "--no-fund", "--no-package-lock", "--ignore-scripts", `--registry=${REGISTRY}`, `@img/sharp-wasm32@${sharpVersion}`],
      { cwd: out, shell, env: { ...process.env, npm_config_registry: REGISTRY } },
    );
  }
  try {
    createRequire(join(out, "package.json")).resolve("@img/sharp-wasm32/sharp.node");
  } catch {
    throw new Error(`@img/sharp-wasm32 ${sharpVersion} did not install into ${wasm}, or does not export sharp.node`);
  }
  for (const entry of readdirSync(imgDir)) {
    if (/^sharp-(libvips-)?linux/.test(entry)) rmSync(join(imgDir, entry), { recursive: true, force: true });
  }
}
const sharpBuild = process.platform === "linux" ? "wasm" : "native";

// ---------------------------------------------------------------- the trim
// prebuilds for the other platforms, and source maps nobody opens in a packaged app
const platformTag = `${process.platform}-${process.arch}`;
const prebuilds = join(out, "node_modules", "node-pty", "prebuilds");
if (existsSync(prebuilds)) {
  for (const entry of readdirSync(prebuilds)) {
    if (entry !== platformTag) rmSync(join(prebuilds, entry), { recursive: true, force: true });
  }
}
let maps = 0;
const walk = (dir) => {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, entry.name);
    if (entry.isSymbolicLink()) continue;
    if (entry.isDirectory()) walk(p);
    else if (entry.name.endsWith(".map")) {
      rmSync(p, { force: true });
      maps += 1;
    }
  }
};
walk(join(out, "node_modules"));
rmSync(join(out, "node_modules", ".package-lock.json"), { force: true });

// ---------------------------------------------------------------- the runtime's seat
// electron-builder copies runtime/ as an extra resource; when the hands' runtime was not
// built (scripts/desktop-app/build-runtime.py --target harness/desktop/runtime), the folder
// still has to exist. The app checks for the executable, not the folder.
const runtimeDir = join(appDir, "runtime");
if (!existsSync(runtimeDir)) {
  mkdirSync(runtimeDir);
  writeFileSync(join(runtimeDir, "README.txt"), "No runtime for the hands was built into this copy of nanoMuse Desktop; `nanomuse` on PATH or NANOMUSE_PY serves them.\n");
}

// ---------------------------------------------------------------- the record
const installed = JSON.parse(readFileSync(join(out, "node_modules", "@deepseek-ai", "dsh", "package.json"), "utf8"));
const bundled = JSON.parse(readFileSync(join(out, "node_modules", "dsh-nanomuse", "package.json"), "utf8"));
if (installed.version !== dshVersion) throw new Error(`npm installed dsh ${installed.version}, wanted ${dshVersion}`);
let files = 0;
let bytes = 0;
const count = (dir) => {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, entry.name);
    if (entry.isSymbolicLink()) continue;
    if (entry.isDirectory()) count(p);
    else {
      files += 1;
      bytes += statSync(p).size;
    }
  }
};
count(join(out, "node_modules"));
const record = {
  dsh: installed.version,
  bundle: bundled.version,
  platform: process.platform,
  arch: process.arch,
  sharp: sharpBuild,
  files,
  megabytes: Math.round(bytes / 1024 / 1024),
  stagedAt: new Date().toISOString(),
};
writeFileSync(join(out, "dsh.json"), `${JSON.stringify(record, null, 2)}\n`);
console.log(`staged ${out}: dsh ${record.dsh}, ${bundled.name} ${record.bundle}, sharp ${sharpBuild}, ${files} files, ${record.megabytes} MB (${maps} source maps dropped)`);
