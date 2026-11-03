// Compatibility seam for the pinned Harness: inherited Cloud capacities are runtime
// defaults, while the settings service continues to expose the person's raw fields.
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const original = "\t\tconst raw = config.providers.get();";
const patched = "\t\tconst configured = config.providers.get();\n\t\tconst raw = ctx.get(\"nanomuseCloud\")?.providerDefaults?.(configured) ?? configured;";

export function capacityDefaultsSource(source) {
  if (source.includes(patched)) return source;
  if (source.split(original).length !== 2) {
    throw new Error("The Harness capacity-default seam changed; review the compatibility patch.");
  }
  return source.replace(original, patched);
}

export function patchCapacityDefaults(stage) {
  const root = join(stage, "node_modules", "@deepseek-ai", "dsh-llm-pi-ai");
  const manifest = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
  if (manifest.version !== "0.2.0-rc.2") {
    throw new Error(`Review Cloud capacity compatibility for dsh-llm-pi-ai ${manifest.version}.`);
  }
  const path = join(root, "lib", "index.js");
  const source = readFileSync(path, "utf8");
  const next = capacityDefaultsSource(source);
  if (next !== source) writeFileSync(path, next);
}
