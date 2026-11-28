// Where the main window may navigate (src/navigation.ts): the Host's origin compared as a
// parsed URL, the shell's own pages from disk, http(s) to the browser, the rest dropped.
import assert from "node:assert/strict";
import { test } from "node:test";
import { mediaPermissionAllowed, navigationVerdict, ownPage, sameOrigin } from "../out/navigation.js";

const HOST = "http://127.0.0.1:38421/?token=abc";
const OWN = "file:///opt/nanoMuse/resources/app.asar/resources";

test("the Host's origin is a parsed origin, not a prefix of the address", () => {
  assert.equal(sameOrigin("http://127.0.0.1:38421/", HOST), true);
  assert.equal(sameOrigin("http://127.0.0.1:38421/sessions/1#x", HOST), true);
  // the Host's origin as the user-info part of another host passed the old prefix test
  assert.equal(sameOrigin("http://127.0.0.1:38421@evil.example/", HOST), false);
  assert.equal(sameOrigin("http://127.0.0.1:384210/", HOST), false);
  assert.equal(sameOrigin("https://127.0.0.1:38421/", HOST), false);
  assert.equal(sameOrigin("http://localhost:38421/", HOST), false);
  assert.equal(sameOrigin("not a url", HOST), false);
  assert.equal(sameOrigin("http://127.0.0.1:38421/", null), false, "nothing is the Host's before it is up");
});

test("only the shell's own pages come from disk", () => {
  assert.equal(ownPage(`${OWN}/loading.html?lang=zh`, OWN), true);
  assert.equal(ownPage(`${OWN}/sub/loading.html`, OWN), true);
  assert.equal(ownPage(`${OWN}/sub/../loading.html`, OWN), true);
  assert.equal(ownPage("file:///etc/passwd", OWN), false);
  assert.equal(ownPage(`${OWN}-other/x.html`, OWN), false, "a sibling directory with the same prefix is not ours");
  assert.equal(ownPage(`${OWN}/`, OWN), false, "the bare directory is not a page");
  assert.equal(ownPage(`${OWN}/../../etc/passwd`, OWN), false, "dot-segments cannot escape ownResources");
  assert.equal(ownPage(`${OWN}/%2e%2e/%2e%2e/etc/passwd`, OWN), false, "percent-encoded dot-segments cannot escape ownResources");
  assert.equal(ownPage(`${OWN}/..%2f..%2fetc%2fpasswd`, OWN), false, "percent-encoded slashes cannot escape ownResources");
  assert.equal(ownPage(`${OWN}/%2e%2e%5c%2e%2e%5csecret.html`, OWN), false, "percent-encoded backslashes cannot escape ownResources");
  assert.equal(ownPage(`file://evil.example/opt/nanoMuse/resources/app.asar/resources/loading.html`, OWN), false, "a file URL with a remote host is not ours");
  assert.equal(ownPage(`${OWN}/%ZZ`, OWN), false, "malformed percent-encoding is refused");
  assert.equal(ownPage("http://127.0.0.1:38421/loading.html", OWN), false);

  const winOwn = "file:///C:/Program%20Files/nanoMuse/resources";
  assert.equal(ownPage(`${winOwn}/loading.html?lang=en`, winOwn), true);
  assert.equal(ownPage(`${winOwn}/..%5c..%5cWindows%5cwin.ini`, winOwn), false);
});

test("the verdict: stay, open outside, or drop", () => {
  assert.equal(navigationVerdict("http://127.0.0.1:38421/x", HOST, OWN), "allow");
  assert.equal(navigationVerdict(`${OWN}/loading.html`, HOST, OWN), "allow");
  assert.equal(navigationVerdict(`${OWN}/%2e%2e/secret.html`, HOST, OWN), "deny");
  assert.equal(navigationVerdict("https://nanomuse.cn/docs/desktop", HOST, OWN), "external");
  assert.equal(navigationVerdict("http://127.0.0.1:38421@evil.example/", HOST, OWN), "external", "to the browser, never into the window");
  assert.equal(navigationVerdict("javascript:alert(1)", HOST, OWN), "deny");
  assert.equal(navigationVerdict("file:///etc/passwd", HOST, OWN), "deny");
  assert.equal(navigationVerdict("data:text/html,<b>x</b>", HOST, OWN), "deny");
});

test("media permission is same-origin audio only", () => {
  const origin = "http://127.0.0.1:38421/dictation";
  assert.equal(mediaPermissionAllowed("media", origin, origin, ["audio"], HOST), true);
  assert.equal(mediaPermissionAllowed("media", origin, origin, ["video"], HOST), false);
  assert.equal(mediaPermissionAllowed("media", origin, origin, ["audio", "video"], HOST), false);
  assert.equal(mediaPermissionAllowed("media", origin, "https://evil.example/", ["audio"], HOST), false);
  assert.equal(mediaPermissionAllowed("media", "https://evil.example/", origin, ["audio"], HOST), false);
  assert.equal(mediaPermissionAllowed("geolocation", origin, origin, ["audio"], HOST), false);
});
