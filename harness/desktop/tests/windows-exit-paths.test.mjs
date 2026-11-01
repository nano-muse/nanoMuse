import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { EventEmitter } from "node:events";
import vm from "node:vm";
import ts from "typescript";
import * as windowPermissions from "../out/window-permissions.js";

// Execute the shipped shell callbacks, with only Electron's window/app side
// effects replaced. AST extraction avoids booting a Host or personal profile.
const source = ts.createSourceFile("main.js", readFileSync(new URL("../out/main.js", import.meta.url), "utf8"), ts.ScriptTarget.Latest, true);
const functions = ["protectedQuit", "mainWindowClosed", "createWindow"].map((name) =>
  source.statements.find((node) => ts.isFunctionDeclaration(node) && node.name?.text === name).getText(source)).join("\n");
const hooks = [];
function collect(node) {
  if (ts.isCallExpression(node) && node.expression.getText(source) === "electron_1.app.on"
      && ts.isStringLiteral(node.arguments[0]) && ["before-quit", "window-all-closed"].includes(node.arguments[0].text)) {
    hooks.push(node.getText(source));
  }
  ts.forEachChild(node, collect);
}
collect(source);

function shell(phase = "ready") {
  const requests = [];
  const noop = () => undefined;
  class Window extends EventEmitter {
    webContents = { send: noop, on: noop, setWindowOpenHandler: noop, session: { setPermissionRequestHandler: noop, setPermissionCheckHandler: noop } };
    loadFile = noop;
  }
  const app = Object.assign(new EventEmitter(), { quit: () => requests.push("app quit") });
  const context = vm.createContext({
    requests, quitting: false, sessionEnding: false, mainWindow: null, tray: null,
    app,
    exitGuard: { requestExit: async (intent) => { requests.push(intent); return false; } },
    windowsUpdates: { quit: async () => { requests.push("update quit"); }, dispose: noop, snapshot: () => ({ phase }) },
    showWindow: () => requests.push("show window"),
    process: { platform: "win32" }, log: noop, BrowserWindow: Window,
    nativeTheme: { shouldUseDarkColors: false }, BASE_DARK: "#000", BASE_LIGHT: "#fff",
    nativeImage: { createFromPath: noop }, iconPath: noop, overlayColors: noop,
    join: (...parts) => parts.join("/"), __dirname: ".", ownResources: () => ".", zh: false,
    releaseAwake: noop, startWatch: null, child: null, operatorServer: null, macHelper: null,
  });
  context.electron_1 = { app, BrowserWindow: Window, nativeTheme: context.nativeTheme, nativeImage: context.nativeImage, globalShortcut: { unregisterAll: noop } };
  context.node_path_1 = { join: context.join };
  context.window_permissions_1 = windowPermissions;
  vm.runInContext(functions, context);
  vm.runInContext(hooks.join(";\n"), context);
  return { context, requests };
}

test("closing to the tray and idling do not request an update installation", () => {
  const { context, requests } = shell();
  context.tray = {};
  vm.runInContext("mainWindowClosed()", context);
  context.app.emit("window-all-closed");
  assert.deepEqual(requests, []);
});

test("closing the main window without a tray is a real protected update quit", () => {
  const { context, requests } = shell();
  vm.runInContext("mainWindowClosed()", context);
  assert.deepEqual(requests, ["update quit"]);
});

test("keeping the work running after the last window closed brings the window back", async () => {
  const { context, requests } = shell("ready");
  vm.runInContext("mainWindowClosed()", context);
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(requests, ["update quit", "show window"]);
});

test("an update whose installer has started is not read as kept running", async () => {
  const { context, requests } = shell("installing");
  vm.runInContext("mainWindowClosed()", context);
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(requests, ["update quit"]);
});

test("an actual session-end window event bypasses installation on shutdown or logoff", () => {
  const { context, requests } = shell();
  const window = vm.runInContext("createWindow()", context);
  window.emit("session-end");
  window.emit("closed");
  assert.deepEqual(requests, ["app quit"]);
});

test("the shell's system/app before-quit callback does not request installation", () => {
  const { context, requests } = shell();
  context.app.emit("before-quit", { preventDefault() { throw new Error("nothing needs stopping"); } });
  vm.runInContext("mainWindowClosed()", context);
  assert.deepEqual(requests, []);
});
