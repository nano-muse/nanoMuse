// The window's history starts at the Host (src/main.ts): the shell shows its own splash
// (resources/loading.html) first, so the Host's page lands on top of it and a back navigation —
// the mouse's side button, alt+left — returns to a page that only ever says *Starting* and has
// no way to load the Host again (#491). A history navigation never goes through `will-navigate`,
// so the splash has to be out of the history once the Host has answered. The shipped shell
// functions are executed with Electron's window side effects replaced (as
// windows-exit-paths.test.mjs does), so neither a Host nor a personal profile is needed.
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";
import vm from "node:vm";

const HOST = "http://127.0.0.1:38421/?token=abc";

const source = ts.createSourceFile("main.js", readFileSync(new URL("../out/main.js", import.meta.url), "utf8"), ts.ScriptTarget.Latest, true);
const functions = ["loadHost", "createWindow", "boot", "showWindow"]
  .map((name) => {
    const node = source.statements.find((statement) => ts.isFunctionDeclaration(statement) && statement.name?.text === name);
    assert.ok(node, `out/main.js has ${name}() to check`);
    return node.getText(source);
  })
  .join("\n");

/** The shell with a window that records what is loaded and when the history is cleared. */
function shell({ loadFails = false } = {}) {
  const events = [];
  const noop = () => undefined;
  class Window extends EventEmitter {
    constructor() {
      super();
      this.loadFile = (path) => events.push(`file ${path}`);
      this.loadURL = async (url) => {
        events.push(`load ${url}`);
        if (loadFails) throw new Error("the Host never came up");
      };
      this.webContents = {
        send: noop,
        on: noop,
        setWindowOpenHandler: noop,
        executeJavaScript: async () => undefined,
        session: { setPermissionRequestHandler: noop },
        navigationHistory: { clear: () => events.push("clear history") },
      };
    }
    isMinimized = () => false;
    restore = noop;
    show = noop;
    focus = noop;
  }
  const context = vm.createContext({
    events,
    mainWindow: null,
    hostUrl: null,
    screenshotFlag: null,
    sessionEnding: false,
    quitting: false,
    log: noop,
    startHost: async () => HOST,
    host_work_1: { HostWork: class HostWork {} },
    electron_1: {
      BrowserWindow: Window,
      nativeTheme: { shouldUseDarkColors: false },
      nativeImage: { createFromPath: noop, isEmpty: () => true },
      shell: { openExternal: noop },
    },
    node_path_1: { join: (...parts) => parts.join("/") },
    node_url_1: { pathToFileURL: (path) => ({ href: `file:///${path}` }) },
    navigation_1: { navigationVerdict: () => "allow" },
    join: (...parts) => parts.join("/"),
    __dirname: ".",
    ownResources: () => "resources",
    iconPath: () => "icon.png",
    overlayColors: () => ({}),
    zh: false,
    BASE_DARK: "#000",
    BASE_LIGHT: "#fff",
    process: { platform: "win32", argv: [] },
    mainWindowClosed: noop,
  });
  vm.runInContext(functions, context);
  return { context, events };
}

test("the splash is shown on its own and the history is left holding it", () => {
  const { context, events } = shell();
  vm.runInContext("createWindow()", context);
  assert.deepEqual(events, ["file resources/loading.html"], "nothing is cleared before the Host has answered");
});

test("boot puts the Host in the window and the history starts with it", async () => {
  const { context, events } = shell();
  await vm.runInContext("boot()", context);
  assert.deepEqual(
    events,
    ["file resources/loading.html", `load ${HOST}`, "clear history"],
    "the splash is shown, the Host lands on top of it, and the history is cleared so the splash is no longer under it",
  );
});

test("a window made later — the tray bringing it back — starts at the Host too", async () => {
  const { context, events } = shell();
  await vm.runInContext("boot()", context);
  events.length = 0;
  vm.runInContext("mainWindow = null", context); // the window was closed; the app stayed in the tray
  vm.runInContext("showWindow()", context);
  await new Promise((resolve) => setImmediate(resolve)); // showWindow does not await the load
  assert.deepEqual(
    events,
    ["file resources/loading.html", `load ${HOST}`, "clear history"],
    "the second way in loads the Host the same way",
  );
});

test("a Host that never comes up keeps its splash, so the failure stays visible", async () => {
  const { context, events } = shell({ loadFails: true });
  await assert.rejects(vm.runInContext("boot()", context), /never came up/);
  assert.deepEqual(events, ["file resources/loading.html", `load ${HOST}`], "nothing is cleared: the splash is still what the window shows");
});
