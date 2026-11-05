import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";
import * as load_close_1 from "../out/load-close.js";

// The window opens on loading.html and then loads the Host; a back press (a mouse's side
// button too) must not return to the splash, which never moves on by itself.
const text = readFileSync(new URL("../out/main.js", import.meta.url), "utf8");
const source = ts.createSourceFile("main.js", text, ts.ScriptTarget.Latest, true);
const loadHost = source.statements
  .find((node) => ts.isFunctionDeclaration(node) && node.name?.text === "loadHost")
  .getText(source);

function fakeWindow(destroyed = false) {
  const calls = [];
  return {
    calls,
    isDestroyed: () => destroyed,
    loadURL: async (url) => { calls.push(`load ${url}`); },
    webContents: { navigationHistory: { clear: () => calls.push("clear history") } },
  };
}

function run(win) {
  const context = vm.createContext({ win, load_close_1 });
  vm.runInContext(loadHost, context);
  return vm.runInContext("loadHost(win, 'http://127.0.0.1:1/')", context);
}

/** The name of the top-level function each `.loadURL(` call in out/main.js sits in. */
function loadURLCallers() {
  const callers = [];
  const visit = (node, top) => {
    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) && node.expression.name.text === "loadURL") {
      callers.push(top);
    }
    ts.forEachChild(node, (child) => visit(child, top));
  };
  for (const statement of source.statements) {
    visit(statement, ts.isFunctionDeclaration(statement) ? statement.name?.text : "(top level)");
  }
  return callers;
}

test("loading the Host drops the splash from the window's history", async () => {
  const win = fakeWindow();
  await run(win);
  assert.deepEqual(win.calls, ["load http://127.0.0.1:1/", "clear history"]);
});

test("a window closed while the Host loads is left alone", async () => {
  const win = fakeWindow(true);
  await run(win);
  assert.deepEqual(win.calls, ["load http://127.0.0.1:1/"]);
});

test("every Host load in the shell goes through loadHost", () => {
  assert.deepEqual(loadURLCallers(), ["loadHost"]);
});

test("a live window's aborted navigation still rejects startup", async () => {
  const win = fakeWindow();
  const aborted = Object.assign(new Error("Navigation replaced"), { code: "ERR_ABORTED" });
  win.loadURL = async () => { throw aborted; };
  await assert.rejects(run(win), (error) => error === aborted);
  assert.deepEqual(win.calls, []);
});

test("closing a loading window consumes its rejection without touching its history", async () => {
  const win = fakeWindow(true);
  win.loadURL = async () => { throw Object.assign(new Error("Window closed"), { code: "ERR_ABORTED" }); };
  await run(win);
  assert.deepEqual(win.calls, []);
});
