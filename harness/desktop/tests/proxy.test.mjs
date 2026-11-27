// The proxy for the model providers (src/proxy.ts): what the Host's environment gets for a
// setting — nothing for none, the two HTTP variables (ALL_PROXY too for SOCKS), NO_PROXY with
// loopback, the default relay and relays from trusted launch configuration, and NODE_USE_ENV_PROXY so
// Node's fetch reads them. Run after `tsc -p tsconfig.json`.
import assert from "node:assert/strict";
import { test } from "node:test";
import { DEFAULT_RELAY_HOST, maskProxyUrl, noProxyList, PROXY_SCHEMES, proxyEnv, trustedRelayHosts, validProxyUrl } from "../out/proxy.js";

test("an address is one of the four schemes with a host, trailing slash dropped", () => {
  assert.deepEqual([...PROXY_SCHEMES], ["http", "https", "socks5", "socks5h"]);
  assert.equal(validProxyUrl("http://127.0.0.1:7890"), "http://127.0.0.1:7890");
  assert.equal(validProxyUrl("  https://proxy.example:3128/  "), "https://proxy.example:3128");
  assert.equal(validProxyUrl("socks5://127.0.0.1:1080"), "socks5://127.0.0.1:1080");
  assert.equal(validProxyUrl("socks5h://proxy.example:1080"), "socks5h://proxy.example:1080");
  assert.equal(validProxyUrl("http://user:pass@proxy.example:8080"), "http://user:pass@proxy.example:8080");
  // not an address: no scheme, a scheme we do not take, no host, a path or query
  for (const bad of ["", "   ", "proxy.example:8080", "ftp://proxy.example:21", "socks4://127.0.0.1:1080", "http://", "socks5://", "http://proxy.example:8080/path", "http://proxy.example:8080?x=1", "not a url"]) {
    assert.equal(validProxyUrl(bad), undefined, bad);
  }
});

test("the screen never shows the password", () => {
  assert.equal(maskProxyUrl("http://user:pass@proxy.example:8080"), "http://•••@proxy.example:8080");
  assert.equal(maskProxyUrl("socks5://alice@proxy.example:1080"), "socks5://•••@proxy.example:1080");
  assert.equal(maskProxyUrl("http://proxy.example:8080"), "http://proxy.example:8080");
  assert.equal(maskProxyUrl(""), "");
});

test("NO_PROXY is loopback, the default relay and trusted extra relays, each once", () => {
  assert.deepEqual(noProxyList([]), ["localhost", "127.0.0.1", "::1", DEFAULT_RELAY_HOST]);
  assert.deepEqual(noProxyList(["https://cloud.nanomuse.cn", "https://Relay.Example:8790/", "relay.example", "", "not a host at all??"]), ["localhost", "127.0.0.1", "::1", "cloud.nanomuse.cn", "relay.example"]);
  // a bare 127.0.0.1:8790 (a self-hosted relay next to the app) adds nothing: loopback is there already
  assert.deepEqual(noProxyList(["http://127.0.0.1:8790"]), ["localhost", "127.0.0.1", "::1", DEFAULT_RELAY_HOST]);
});

test("extra relay exceptions come only from trusted process configuration", () => {
  assert.deepEqual(trustedRelayHosts({}), []);
  assert.deepEqual(trustedRelayHosts({ NANOMUSE_CLOUD_URL: "https://relay.example:8790" }), ["https://relay.example:8790"]);
});

test("nothing is set when there is no proxy or it is not an address", () => {
  assert.deepEqual(proxyEnv(undefined), {});
  assert.deepEqual(proxyEnv(""), {});
  assert.deepEqual(proxyEnv("   "), {});
  assert.deepEqual(proxyEnv("ftp://proxy.example:21"), {});
  assert.deepEqual(proxyEnv("proxy.example:8080"), {});
});

test("an HTTP proxy sets the two variables, NO_PROXY and the Node switch", () => {
  const env = proxyEnv("http://proxy.example:8080/", ["https://relay.example"]);
  assert.deepEqual(env, {
    HTTP_PROXY: "http://proxy.example:8080",
    HTTPS_PROXY: "http://proxy.example:8080",
    NO_PROXY: "localhost,127.0.0.1,::1,cloud.nanomuse.cn,relay.example",
    NODE_USE_ENV_PROXY: "1",
  });
  assert.equal("ALL_PROXY" in env, false, "ALL_PROXY is for SOCKS only");
});

test("a SOCKS proxy sets ALL_PROXY as well, for the runtime's httpx", () => {
  const env = proxyEnv("socks5h://127.0.0.1:1080");
  assert.equal(env.HTTP_PROXY, "socks5h://127.0.0.1:1080");
  assert.equal(env.HTTPS_PROXY, "socks5h://127.0.0.1:1080");
  assert.equal(env.ALL_PROXY, "socks5h://127.0.0.1:1080");
  assert.equal(env.NO_PROXY, "localhost,127.0.0.1,::1,cloud.nanomuse.cn");
  assert.equal(env.NODE_USE_ENV_PROXY, "1");
});
