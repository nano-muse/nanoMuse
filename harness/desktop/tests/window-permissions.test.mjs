import assert from "node:assert/strict";
import { test } from "node:test";
import { editContextMenu, installWindowPermissions } from "../out/window-permissions.js";

const origin = "http://127.0.0.1:38421";
const details = { requestingUrl: `${origin}/settings`, isMainFrame: true };

function windowPermissions() {
  let host = origin;
  let url = `${origin}/chat`;
  let request, check;
  const contents = {
    getURL: () => url,
    session: {
      setPermissionRequestHandler: (handler) => { request = handler; },
      setPermissionCheckHandler: (handler) => { check = handler; },
    },
  };
  installWindowPermissions(contents, () => host);
  return {
    contents,
    navigate: (next) => { url = next; },
    restart: (next) => { host = next; },
    request: (permission, data = details, requester = contents) => {
      let result;
      request(requester, permission, (allowed) => { result = allowed; }, data);
      return result;
    },
    check: (permission, data = details, from = origin, requester = contents) => check(requester, permission, from, data),
  };
}

test("copy buttons can write from the app's main page on both permission paths", () => {
  const w = windowPermissions();
  assert.equal(w.check("clipboard-sanitized-write"), true);
  assert.equal(w.request("clipboard-sanitized-write"), true);
  for (const permission of ["clipboard-read", "deprecated-sync-clipboard-read", "geolocation", "unknown"]) {
    assert.equal(w.check(permission), false);
    assert.equal(w.request(permission), false);
  }
});

test("embedded, unrelated, stale and worker contexts cannot write the clipboard", () => {
  const w = windowPermissions();
  const permission = "clipboard-sanitized-write";
  for (const data of [
    { ...details, isMainFrame: false },
    { ...details, requestingUrl: "https://external.example/" },
    { ...details, requestingUrl: `${origin}@external.example/` },
    { ...details, requestingUrl: undefined },
  ]) {
    assert.equal(w.check(permission, data), false);
    assert.equal(w.request(permission, data), false);
  }
  assert.equal(w.check(permission, details, origin, null), false);
  assert.equal(w.check(permission, details, "https://external.example"), false);
  assert.equal(w.request(permission, details, {}), false);
  w.navigate("https://external.example/");
  assert.equal(w.check(permission), false);
  assert.equal(w.request(permission), false);
  w.navigate(origin);
  w.restart("http://127.0.0.1:38422");
  assert.equal(w.check(permission), false);
  assert.equal(w.request(permission), false);
  w.restart(null);
  assert.equal(w.check(permission), false);
  assert.equal(w.request(permission), false);
});

test("dictation still permits same-origin audio and denies cameras and other frames", () => {
  const w = windowPermissions();
  assert.equal(w.request("media", { ...details, mediaTypes: ["audio"], securityOrigin: origin }), true);
  assert.equal(w.check("media", { ...details, mediaType: "audio", securityOrigin: origin }), true);
  for (const mediaTypes of [["video"], ["audio", "video"], []]) {
    assert.equal(w.request("media", { ...details, mediaTypes }), false);
  }
  for (const mediaType of ["video", "unknown", undefined]) {
    assert.equal(w.check("media", { ...details, mediaType }), false);
  }
  assert.equal(w.check("media", { ...details, mediaType: "audio", embeddingOrigin: "https://external.example" }), false);
  assert.equal(w.request("media", { ...details, mediaTypes: ["audio"], securityOrigin: "https://external.example" }), false);
});

test("right-click editing respects native flags and only offers actions on editable or selected text", () => {
  const flags = { canCut: false, canCopy: false, canPaste: true, canSelectAll: true };
  const items = editContextMenu({ isEditable: true, selectionText: "", editFlags: flags });
  assert.deepEqual(items.filter((item) => item.role).map(({ role, enabled }) => [role, enabled]), [
    ["cut", false], ["copy", false], ["paste", true], ["selectAll", true],
  ]);
  assert.deepEqual(editContextMenu({ isEditable: false, selectionText: "selected", editFlags: { ...flags, canCopy: true } }), [{ role: "copy", enabled: true }]);
  assert.deepEqual(editContextMenu({ isEditable: false, selectionText: "", editFlags: flags }), []);
});
