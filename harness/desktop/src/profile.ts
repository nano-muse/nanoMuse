import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { relink } from "./profile-link";

export const PROFILE = "nanomuse";
export const BUNDLE = "dsh-nanomuse";
// The initial composition includes Schedule for goals and reminders. Later launches use
// the saved selection, including optional bundles the person enabled or disabled.
const DEFAULT_BUNDLES = ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app", "@deepseek-ai/dsh-experimental-schedule-bundle", BUNDLE];

/**
 * The profile the Host boots: `~/.nanomuse/desktop/profiles/nanomuse`. Three small files the
 * harness reads (the manifest with the bundle list, the empty root, the person's own patch
 * layer, which dsh writes settings into) and one link: `node_modules/dsh-nanomuse` → the copy
 * under resources, which is how the Loader finds a bundle that is not among the harness's own
 * packages. The link is refreshed every start, so moving the app or updating it is enough.
 */
export function ensureProfile(home: string, dshDir: string, log: (message: string) => void): string {
  const dir = join(home, "profiles", PROFILE);
  mkdirSync(join(dir, "node_modules"), { recursive: true });
  const manifestPath = join(dir, "package.json");
  let manifest: Record<string, unknown> = {};
  if (existsSync(manifestPath)) {
    try {
      manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as Record<string, unknown>;
    } catch (exc) {
      log(`profile manifest unreadable, rewriting: ${String(exc)}`);
    }
  }
  const deps = (manifest.dependencies as Record<string, string> | undefined) ?? {};
  const dsh = (manifest.dsh as { profile?: { bundles?: string[] } } | undefined) ?? {};
  // Plugin settings persist their selection here. Seed defaults only before a selection
  // exists: an empty list and a missing optional bundle are also deliberate choices.
  const bundles = dsh.profile?.bundles;
  if (bundles === undefined || deps[BUNDLE] !== "*" || manifest.name !== `dsh-profile-${PROFILE}`) {
    const next = {
      ...manifest,
      name: `dsh-profile-${PROFILE}`,
      private: true,
      dependencies: { ...deps, [BUNDLE]: "*" },
      dsh: { ...dsh, profile: { ...dsh.profile, bundles: bundles ?? [...DEFAULT_BUNDLES] } },
    };
    writeFileSync(manifestPath, `${JSON.stringify(next, null, 2)}\n`);
  }
  if (!existsSync(join(dir, "cordis.yml"))) {
    writeFileSync(
      join(dir, "cordis.yml"),
      "# dsh profile root — an empty entry list. The tree is composed as patches:\n# each bundle in package.json's dsh.profile.bundles, then cordis.patch.yml.\n# Edit cordis.patch.yml, not this file.\n[]\n",
    );
  }
  if (!existsSync(join(dir, "cordis.patch.yml"))) {
    writeFileSync(
      join(dir, "cordis.patch.yml"),
      "# Your patch layer for this dsh profile, applied after every bundle layer:\n# a top-level YAML array of loader patch entries. nanoMuse Desktop and dsh\n# write settings here; you may edit it too.\n[]\n",
    );
  }
  const link = join(dir, "node_modules", BUNDLE);
  const target = join(dshDir, "node_modules", BUNDLE);
  if (relink(link, target)) log(`profile: ${BUNDLE} → ${target}`);
  return dir;
}

