import assert from "node:assert/strict";
import { test } from "node:test";
import { closedDuringLoad } from "../out/load-close.js";

test("a destroyed window no longer needs a Host page", () => {
  assert.equal(closedDuringLoad({ isDestroyed: () => true }), true);
});

test("a live window still needs its Host load to succeed", () => {
  assert.equal(closedDuringLoad({ isDestroyed: () => false }), false);
});
