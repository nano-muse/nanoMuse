// What the staged harness carries on Linux (scripts/prepare-dsh.mjs): sharp's WebAssembly
// build and not its native one. The Host runs inside the Electron binary, whose Linux build
// links the system's GLib and leaks its symbols into the process; sharp's prebuilt libvips
// carries a GLib of its own, and on some systems the clash is a SIGSEGV on the first picture
// decoded, which kills the Host mid-turn (#274). sharp's loader falls through to
// @img/sharp-wasm32 when the platform's prebuild is absent, so the fix is what the package
// does and does not contain. The script runs on import, so this reads it.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const script = readFileSync(new URL("../scripts/prepare-dsh.mjs", import.meta.url), "utf8");

/** The regular expression the script drops native sharp packages by, as written there. */
function dropRule() {
  const m = script.match(/if \((\/\^sharp-[^/]+\/)\.test\(entry\)\) rmSync\(join\(imgDir, entry\)/);
  assert.ok(m, "the script removes @img entries by one regular expression");
  const source = m[1].slice(1, -1);
  return new RegExp(source);
}

test("on Linux the staged harness swaps sharp's native build for the WebAssembly one", () => {
  const start = script.indexOf("sharp on Linux");
  assert.notEqual(start, -1);
  const step = script.slice(start, script.indexOf("the trim", start));
  // only on Linux: macOS and Windows keep the native build, which has no GLib to clash with
  assert.match(step, /if \(process\.platform === "linux"\) \{/);
  // the wasm package at sharp's own version, from the public registry, scripts off
  assert.match(step, /@img\/sharp-wasm32@\$\{sharpVersion\}/);
  assert.match(step, /--ignore-scripts/);
  assert.match(step, /--registry=\$\{REGISTRY\}/);
  // a missing wasm build is a failed staging, not a package that crashes later
  assert.match(step, /throw new Error\(`@img\/sharp-wasm32/);
  // and the record says which build went in
  assert.match(script, /sharp: sharpBuild,/);
  assert.match(script, /const sharpBuild = process\.platform === "linux" \? "wasm" : "native";/);
});

test("the drop rule takes the native Linux packages and nothing else", () => {
  const drop = dropRule();
  for (const native of ["sharp-linux-x64", "sharp-libvips-linux-x64", "sharp-linux-arm64", "sharp-libvips-linux-arm64", "sharp-linuxmusl-x64", "sharp-libvips-linuxmusl-x64"]) {
    assert.ok(drop.test(native), `${native} is dropped`);
  }
  for (const kept of ["sharp-wasm32", "colour", "sharp-darwin-arm64", "sharp-libvips-darwin-arm64", "sharp-win32-x64"]) {
    assert.ok(!drop.test(kept), `${kept} stays`);
  }
});
