// What the installers carry (electron-builder.yml): the face's clips must reach a Windows
// install. electron-builder's NSIS target keeps "pre-compressed" extensions (.mp4 among them by
// default) out of the installer's archive and writes those files one by one instead, skipping
// every node_modules folder as it goes, so the dragon's clips under
// resources/dsh/node_modules/dsh-nanomuse/assets/ were in neither place and the face above the
// chat stood still on Windows (1.0.0). The config turns the exception off; this keeps it off.
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const here = new URL("..", import.meta.url);
const config = readFileSync(new URL("electron-builder.yml", here), "utf8");

/** The lines of one top-level block of the YAML, by its key. */
function block(key) {
  const lines = config.split("\n");
  const start = lines.findIndex((line) => line === `${key}:`);
  assert.notEqual(start, -1, `electron-builder.yml has a ${key} block`);
  const body = [];
  for (const line of lines.slice(start + 1)) {
    if (line && !line.startsWith(" ") && !line.startsWith("#")) break;
    body.push(line);
  }
  return body;
}

test("the NSIS installer puts every file in its archive, the face's clips included", () => {
  const nsis = block("nsis").filter((line) => !line.trim().startsWith("#"));
  assert.ok(nsis.includes("  preCompressedFileExtensions: []"), "nsis.preCompressedFileExtensions is an empty list");
});

test("the clips the installer must carry are in the bundle's assets", () => {
  const assets = fileURLToPath(new URL("../dsh-nanomuse/assets/", here));
  for (const mood of ["idle", "working", "waiting", "happy"]) {
    assert.ok(existsSync(join(assets, `dragon-${mood}.mp4`)), `dragon-${mood}.mp4`);
    assert.ok(existsSync(join(assets, `dragon-${mood}.webp`)), `dragon-${mood}.webp`);
  }
});
