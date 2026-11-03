// Exercise the same file initialization that runs before each desktop Host start.
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { ensureProfile } from "../out/profile.js";
import { linkTarget, sameTarget } from "../out/profile-link.js";

const base = "@deepseek-ai/dsh-base";
const web = "@deepseek-ai/dsh-web-app";
const schedule = "@deepseek-ai/dsh-experimental-schedule-bundle";
const teams = "@deepseek-ai/dsh-experimental-agent-team-profile";
const review = "@deepseek-ai/dsh-experimental-auto-review";
const voice = "@deepseek-ai/dsh-experimental-voice-input-bundle";
const defaults = [base, web, schedule, "dsh-nanomuse"];

function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), "nm-profile-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const home = join(root, "home");
  const dsh = join(root, "resources", "dsh");
  mkdirSync(join(dsh, "node_modules", "dsh-nanomuse"), { recursive: true });
  const dir = join(home, "profiles", "nanomuse");
  mkdirSync(dir, { recursive: true });
  const manifest = join(dir, "package.json");
  return {
    root, home, dsh, dir,
    start: () => ensureProfile(home, dsh, () => {}),
    read: () => JSON.parse(readFileSync(manifest, "utf8")),
    text: () => readFileSync(manifest, "utf8"),
    write: (value) => writeFileSync(manifest, `${JSON.stringify(value, null, 4)}\n`),
  };
}

test("a new profile gets the existing defaults, and later starts leave it alone", (t) => {
  const f = fixture(t);
  assert.equal(f.start(), f.dir);
  assert.deepEqual(f.read().dsh.profile.bundles, defaults);
  assert.equal(f.read().dependencies["dsh-nanomuse"], "*");
  const before = f.text();
  f.start();
  assert.equal(f.text(), before);
  assert.ok(sameTarget(linkTarget(join(f.dir, "node_modules", "dsh-nanomuse")),
    join(f.dsh, "node_modules", "dsh-nanomuse")));
});

test("enabled bundles and their saved order survive repeated desktop starts", (t) => {
  const f = fixture(t);
  f.start();
  const manifest = f.read();
  const bundles = [base, web, "dsh-nanomuse", teams, review, schedule, voice, "custom-bundle"];
  manifest.dsh.profile.bundles = bundles;
  manifest.dependencies["custom-bundle"] = "1.0.0";
  f.write(manifest);
  const before = f.text();
  for (let i = 0; i < 2; i += 1) {
    f.start();
    assert.deepEqual(f.read().dsh.profile.bundles, bundles);
    assert.equal(f.text(), before, "startup must not rewrite a saved selection");
  }
});

test("turning optional bundles off, including Schedule, survives repeated starts", (t) => {
  const f = fixture(t);
  f.start();
  let manifest = f.read();
  manifest.dsh.profile.bundles.push(teams, review);
  f.write(manifest);
  f.start();
  manifest = f.read();
  manifest.dsh.profile.bundles = manifest.dsh.profile.bundles.filter(
    (name) => ![teams, review, schedule].includes(name),
  );
  f.write(manifest);
  for (let i = 0; i < 2; i += 1) {
    f.start();
    assert.deepEqual(f.read().dsh.profile.bundles, [base, web, "dsh-nanomuse"]);
  }
});

test("an explicitly empty bundle selection is not mistaken for a new profile", (t) => {
  const f = fixture(t);
  f.write({ name: "old-profile", dsh: { profile: { bundles: [] } } });
  f.start();
  f.start();
  assert.deepEqual(f.read().dsh.profile.bundles, []);
});

test("metadata and app-link repairs preserve plugin selections and patch files", (t) => {
  const f = fixture(t);
  f.start();
  const manifest = f.read();
  const bundles = [base, web, "dsh-nanomuse", review, teams];
  manifest.name = "old-profile";
  manifest.dependencies["dsh-nanomuse"] = "old-version";
  manifest.dependencies["custom-bundle"] = "1.0.0";
  manifest.dsh.profile = { bundles, custom: true };
  manifest.dsh.custom = { retained: true };
  manifest.custom = ["retained"];
  f.write(manifest);
  const root = "# Existing root\n[]\n";
  const patch = "# Keep the person's settings\n- id: schedule\n  disabled: true\n";
  writeFileSync(join(f.dir, "cordis.yml"), root);
  writeFileSync(join(f.dir, "cordis.patch.yml"), patch);

  const moved = join(f.root, "new-install", "dsh");
  mkdirSync(join(moved, "node_modules", "dsh-nanomuse"), { recursive: true });
  rmSync(f.dsh, { recursive: true });
  ensureProfile(f.home, moved, () => {});
  assert.deepEqual(f.read(), {
    ...manifest,
    name: "dsh-profile-nanomuse",
    dependencies: { ...manifest.dependencies, "dsh-nanomuse": "*" },
  });
  assert.equal(readFileSync(join(f.dir, "cordis.yml"), "utf8"), root);
  assert.equal(readFileSync(join(f.dir, "cordis.patch.yml"), "utf8"), patch);
  assert.ok(sameTarget(linkTarget(join(f.dir, "node_modules", "dsh-nanomuse")),
    join(moved, "node_modules", "dsh-nanomuse")));
});

test("a profile without a bundle list gets defaults without losing other metadata", (t) => {
  const f = fixture(t);
  f.write({
    name: "dsh-profile-nanomuse",
    dependencies: { "dsh-nanomuse": "*", "custom-bundle": "1.0.0" },
    dsh: { profile: { custom: true } },
  });
  f.start();
  assert.deepEqual(f.read().dsh.profile, { custom: true, bundles: defaults });
  assert.equal(f.read().dependencies["custom-bundle"], "1.0.0");
});
