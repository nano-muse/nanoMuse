// The port the window's origin lives on (src/host-port.ts): the remembered port is tried
// first, and a fallback never overwrites the memory — an orphaned Host holding the port is
// a this-launch condition, and writing the fallback down would strand the origin's storage
// behind a port the app never serves on again. Run after `tsc -p tsconfig.json`.
import assert from "node:assert/strict";
import { test } from "node:test";
import { chooseHostPort, HOST_PORT_DEFAULT } from "../out/host-port.js";

/** A fake home: what `<home>/port` says, which ports are taken, and what a random bind gives. */
function io({ remembered = 0, taken = [], random = 49152 } = {}) {
  const writes = [];
  return {
    writes,
    readRemembered: () => remembered,
    writeRemembered: (port) => writes.push(port),
    tryPort: async (port) => (taken.includes(port) ? 0 : port === 0 ? random : port),
  };
}

test("a free remembered port is used and kept", async () => {
  const home = io({ remembered: 39000 });
  const choice = await chooseHostPort(home);
  assert.equal(choice.port, 39000);
  assert.equal(choice.remembered, true);
  assert.deepEqual(home.writes, [39000]);
});

test("a taken remembered port falls back for the launch without overwriting the memory", async () => {
  const home = io({ remembered: 39000, taken: [39000] });
  const choice = await chooseHostPort(home);
  assert.equal(choice.port, HOST_PORT_DEFAULT);
  assert.equal(choice.remembered, false);
  assert.deepEqual(home.writes, []);
});

test("with the default taken too, the random fallback still leaves the memory alone", async () => {
  const home = io({ remembered: 39000, taken: [39000, HOST_PORT_DEFAULT] });
  const choice = await chooseHostPort(home);
  assert.equal(choice.port, 49152);
  assert.equal(choice.remembered, false);
  assert.deepEqual(home.writes, []);
});

test("a fresh install remembers the default it binds", async () => {
  const home = io();
  const choice = await chooseHostPort(home);
  assert.equal(choice.port, HOST_PORT_DEFAULT);
  assert.equal(choice.remembered, true);
  assert.deepEqual(home.writes, [HOST_PORT_DEFAULT]);
});

test("a fresh install whose default is taken remembers the random port instead", async () => {
  const home = io({ taken: [HOST_PORT_DEFAULT] });
  const choice = await chooseHostPort(home);
  assert.equal(choice.port, 49152);
  assert.equal(choice.remembered, true);
  assert.deepEqual(home.writes, [49152]);
});

test("the launch after a fallback reclaims the remembered port once its taker is gone", async () => {
  const orphanHolds = [39000];
  const home = io({ remembered: 39000, taken: orphanHolds, random: 50000 });
  const fallback = await chooseHostPort(home);
  assert.equal(fallback.remembered, false);
  assert.deepEqual(home.writes, []);
  orphanHolds.length = 0; // the orphaned Host dies
  const next = await chooseHostPort({ ...home, tryPort: async (port) => (port === 0 ? 50000 : port) });
  assert.equal(next.port, 39000);
  assert.equal(next.remembered, true);
});
