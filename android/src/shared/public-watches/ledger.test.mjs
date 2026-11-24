import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const assets = ["android/app/src/main/assets/nanomuse", "ios/NanoMuse/Resources"];
const copies = assets.map((dir) =>
  readFileSync(new URL("../../" + dir + "/public-watches.js", import.meta.url), "utf8"),
);
assert.equal(copies[0], copies[1]);
const engine = vm.createContext({});
vm.runInContext(copies[0], engine);
const HOUR = 3600000;

function phone() {
  let state = {},
    now = 1770000000000,
    sequence = 0;
  const run = (op = "view", fields = {}) => {
    const view = JSON.parse(engine.NanoMuseWatch(JSON.stringify({ op, state, now, ...fields })));
    state = JSON.parse(JSON.stringify(view.state)); // persist across processes
    return view;
  };
  return {
    run,
    edit: (fields) => run("edit", { revision: run().revision, ...fields }),
    turn: (text, personal = true, id = String(++sequence)) =>
      run("observe", { turns: [{ id, at: now, personal, text }] }),
    advance: (hours) => {
      now += hours * HOUR;
    },
  };
}

test("discovery only promotes direct declarations and explicit requests", () => {
  const samples = [
    ["我的 GitHub 用户名是 Example-Org。", "github_user", "example-org", "active"],
    ["我在 GitHub 上开源的仓库是 https://github.com/Example/Repo。", "github_repo", "example/repo", "active"],
    ["I contribute to https://github.com/Example/Repo", "github_repo", "example/repo", "suggested"],
    ["请持续跟踪对抗鲁棒性相关的新论文。", "research_topic", "对抗鲁棒性", "active"],
    ["I study multimodal retrieval.", "research_topic", "multimodal retrieval", "suggested"],
    ["My OpenAlex ID is A123456.", "research_author", "A123456", "active"],
    ["My paper is 10.5555/Sample.", "research_work", "10.5555/sample", "active"],
    [
      "我的谷歌学术主页是 https://scholar.google.com/citations?user=aBcD_234efGH。",
      "scholar_profile",
      "aBcD_234efGH",
      "suggested",
    ],
    ["请关注这个网站 https://example.org/lab", "feed", "https://example.org/lab", "active"],
  ];
  for (const [text, kind, target, status] of samples) {
    const watch = phone().turn(text).watches[0];
    assert.deepEqual(watch && [watch.kind, watch.target, watch.status], [kind, target, status], text);
  }
  const host = phone();
  assert.equal(host.turn("My GitHub handle is @example-org", false).watches[0].status, "suggested");
  assert.equal(host.run().due.length, 0);
});

test("cross-turn references need distinct user turns and never activate rejected identities", () => {
  const host = phone(),
    ref = "https://github.com/example/kit/issues/11";
  for (const text of [
    "Forwarded message:\nMy GitHub handle is @other-org",
    "My repo is https://github.com/example/kit\n不要关注",
    "Watch this site https://example.org/path?token=private",
    "> I maintain https://github.com/example/kit",
    "My private repo is https://github.com/example/kit",
  ]) {
    assert.deepEqual(host.turn(text).watches, []);
  }
  host.turn(ref, true, "a");
  assert.deepEqual(host.turn(ref, true, "a").watches, []);
  const [row] = host.turn(ref.replace("11", "15"), true, "b").watches;
  assert.deepEqual([row.target, row.status], ["example/kit", "suggested"]);
  host.edit({ id: row.id, action: "dismiss" });
  assert.deepEqual(host.turn("I maintain https://github.com/example/kit").watches, []);
  assert.equal(JSON.stringify(host.run().state).includes("private repo"), false);
});

test("Scholar needs an exact research identifier, stale edits cannot re-enable polling", () => {
  const host = phone(),
    [scholar] = host.turn(
      "My Google Scholar profile is https://scholar.google.com/citations?user=abcDEF_8",
    ).watches;
  assert.equal(host.edit({ id: scholar.id, action: "confirm" }).error, "invalid_target");
  assert.equal(host.run().due.length, 0);
  const off = host.edit({ enabled: false });
  assert.equal(host.run("edit", { enabled: true, revision: off.revision - 1 }).error, "stale");
  assert.deepEqual(host.turn("My paper is 10.5555/other").due, []);
  host.edit({ enabled: true });
  assert.equal(
    host.edit({ id: scholar.id, action: "confirm", kind: "research_work", target: "10.5555/example" })
      .watches[0].status,
    "active",
  );
});

function article(n) {
  return { key: "post-" + n, text: "Announcement " + n, url: "https://example.org/post/" + n };
}

test("restored state observes deltas, errors retry, unavailable feeds keep their baseline", () => {
  const host = phone();
  const id = host.edit({ kind: "feed", target: "https://example.org/" }).due[0].id;
  const sample = (items, source = "https://example.org/rss") => host.run("sample", { id, items, source });
  assert.deepEqual(sample([article(1)]).pending, []);
  host.advance(3);
  assert.equal(host.run().due.length, 0);
  host.advance(1);
  assert.equal(host.run().due.length, 1);
  host.run("sample", { id, failed: true });
  assert.equal(host.run().watches[0].unavailable, true);
  host.advance(0.25);
  assert.equal(host.run().due.length, 1);
  assert.deepEqual(
    sample([article(2), article(1)]).pending.map((i) => i.key),
    ["post-2"],
  );
  assert.deepEqual(host.run("consume", { keys: ["post-2"] }).pending, []);
  assert.deepEqual(sample([article(1), article(2)]).pending, []);
  assert.deepEqual(sample([article(3)], "https://example.org/atom").pending, []);
  assert.equal(sample([article(4)], "https://example.org/atom").pending.length, 1);
  host.advance(24 * 8);
  assert.deepEqual(host.run().pending, []);
  host.edit({ id, action: "pause" });
  assert.equal(host.run().due.length, 0);
  host.edit({ id, action: "resume" });
  assert.deepEqual(sample([article(5)]).pending, []);
  host.edit({ enabled: false });
  assert.deepEqual(sample([article(6)]).pending, []);
  host.edit({ enabled: true });
  assert.deepEqual(sample([article(7)]).pending, []);
});

test("same evidence across watches is reviewed once, empty first sample is valid", () => {
  const host = phone(),
    [a, b] = ["repo-one", "repo-two"].map(
      (name) => host.edit({ kind: "github_repo", target: "example/" + name }).watches.at(-1).id,
    );
  for (const id of [a, b]) host.run("sample", { id, items: [] });
  for (const id of [a, b]) host.run("sample", { id, items: [article(7)] });
  assert.equal(host.run().pending.length, 1);
  host.run("consume", { keys: ["post-7"] });
  assert.deepEqual(host.run().pending, []);
  assert.deepEqual(host.run("sample", { id: a, items: [article(7)] }).pending, []);
  const id = host.edit({ kind: "research_topic", target: "speech recognition" }).watches.at(-1).id;
  host.run("sample", { id, items: [] });
  host.advance(5);
  assert.equal(
    host.run().due.some((w) => w.id === id),
    false,
  );
  host.advance(19);
  assert.equal(
    host.run().due.some((w) => w.id === id),
    true,
  );
});
