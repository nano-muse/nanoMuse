// Which loadURL rejections are only the window going away (src/load-close.ts): closing the
// window mid-load rejects the pending load with ERR_ABORTED or, once the window is gone,
// "Object has been destroyed", and neither is a start failure — before the classification,
// closing the window during the load failed the whole boot with a "could not start" dialog
// and a quit. Run after `tsc -p tsconfig.json`.
import assert from "node:assert/strict";
import { test } from "node:test";
import { closedDuringLoad } from "../out/load-close.js";

const live = { isDestroyed: () => false };
const gone = { isDestroyed: () => true };

test("an ERR_ABORTED rejection is the close, not a failure", () => {
  const aborted = Object.assign(new Error("Navigation failed"), { code: "ERR_ABORTED" });
  assert.equal(closedDuringLoad(live, aborted), true);
});

test("a window already destroyed rejects as destroyed, not failed", () => {
  const destroyed = new Error("Object has been destroyed");
  assert.equal(closedDuringLoad(gone, destroyed), true);
});

test("any other rejection is a real load failure", () => {
  assert.equal(closedDuringLoad(live, new Error("ERR_CONNECTION_REFUSED")), false);
  assert.equal(closedDuringLoad(live, Object.assign(new Error("no net"), { code: "ERR_CONNECTION_REFUSED" })), false);
  assert.equal(closedDuringLoad(live, "not even an error object"), false);
});
