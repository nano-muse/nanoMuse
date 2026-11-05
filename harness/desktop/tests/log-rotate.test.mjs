// The desktop's own log steps aside at the runtime's rotation mark (src/log-rotate.ts):
// `<home>/desktop.log` was appended line by line without ever being looked at again, so a
// long-lived install grew it without bound — the Host's stdout and stderr all land there.
// Run after `tsc -p tsconfig.json`.
import assert from "node:assert/strict";
import { test } from "node:test";
import { LOG_ROTATE_BYTES, rotateLogIfNeeded } from "../out/log-rotate.js";

/** A fake home: what the log and its aside file look like. */
function io({ log = undefined, aside = undefined } = {}) {
  const files = new Map(Object.entries({ log, aside }).filter(([, v]) => v !== undefined));
  return {
    files,
    sizeOf: (path) => (path.endsWith("desktop.log") ? files.get("log") : files.get("aside")),
    remove: (path) => files.delete(path.endsWith(".1") ? "aside" : "log"),
    rename: (from, to) => {
      assert.ok(from.endsWith("desktop.log") && to.endsWith("desktop.log.1"), `renamed ${from} -> ${to}`);
      files.set("aside", files.get("log"));
      files.delete("log");
    },
  };
}

test("a log below the mark is left alone", () => {
  const home = io({ log: LOG_ROTATE_BYTES - 1 });
  rotateLogIfNeeded("/home", home);
  assert.equal(home.files.get("log"), LOG_ROTATE_BYTES - 1);
  assert.equal(home.files.has("aside"), false);
});

test("a log past the mark steps aside as .1, replacing the earlier aside", () => {
  const home = io({ log: LOG_ROTATE_BYTES, aside: "the older one" });
  rotateLogIfNeeded("/home", home);
  assert.equal(home.files.has("log"), false);
  assert.equal(home.files.get("aside"), LOG_ROTATE_BYTES);
});

test("a home with no log yet is a no-op", () => {
  const home = io();
  rotateLogIfNeeded("/home", home);
  assert.equal(home.files.size, 0);
});

test("rotation trouble is swallowed so the line still lands", () => {
  const home = io({ log: LOG_ROTATE_BYTES * 2 });
  home.rename = () => {
    throw new Error("locked by the issue dialog's reader");
  };
  rotateLogIfNeeded("/home", home);
  assert.equal(home.files.get("log"), LOG_ROTATE_BYTES * 2);
});
