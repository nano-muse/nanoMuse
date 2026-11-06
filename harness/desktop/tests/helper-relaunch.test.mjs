import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";
import ts from "typescript";

// Run the shipped IPC handler and relaunch function without starting Electron or the Host.
const source = ts.createSourceFile("main.js", readFileSync(new URL("../out/main.js", import.meta.url), "utf8"), ts.ScriptTarget.Latest, true);
const relaunch = source.statements.find((node) => ts.isFunctionDeclaration(node) && node.name?.text === "relaunchNow").getText(source);
let handler;
function collect(node) {
  if (ts.isCallExpression(node) && node.expression.getText(source) === "electron_1.ipcMain.handle"
      && ts.isStringLiteral(node.arguments[0]) && node.arguments[0].text === "nanomuse:relaunch") handler = node.getText(source);
  ts.forEachChild(node, collect);
}
collect(source);

function shell(restart) {
  const helper = { present: () => true, restart, failure: () => "no port after 10 s" };
  let invoke;
  const context = vm.createContext({
    helper: () => helper, macHelper: helper, log: () => undefined,
    relaunching: false, exitGuard: null,
    electron_1: { ipcMain: { handle: (_name, callback) => { invoke = callback; } } },
  });
  vm.runInContext(relaunch + "\n" + handler, context);
  return () => invoke();
}

test("the relaunch IPC waits for the replacement helper", async () => {
  let finish;
  const pending = new Promise((resolve) => { finish = resolve; });
  const invoke = shell(() => pending);
  let answered = false;
  const result = invoke().then((ok) => { answered = true; return ok; });
  await Promise.resolve();
  assert.equal(answered, false);
  finish(true);
  assert.equal(await result, true);
});

test("a failed helper restart reaches the renderer with the startup failure", async () => {
  const invoke = shell(async () => false);
  await assert.rejects(invoke(), /no port after 10 s/);
});
