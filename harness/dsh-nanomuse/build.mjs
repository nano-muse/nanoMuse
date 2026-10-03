#!/usr/bin/env node
/**
 * Build both halves of dsh-nanomuse into lib/.
 *
 *   host:   src/index.ts, src/cloud.ts -> lib/index.js, lib/cloud.js (ESM for Node;
 *           the harness packages are externals so the running dsh's instances are shared)
 *   client: src/client/index.ts -> lib/client.js in the client module system's
 *           lazy-CJS factory format (see DeepSeek Harness, packages/client/modules):
 *
 *             window.__ModuleLoader__.load({ id: 'dsh-nanomuse', factory: (require) => {
 *               var module = { exports: {} }; var exports = module.exports;
 *               …bundle…
 *               return module.exports; } });
 *
 *           React, Cordis and the shared UI libraries resolve through the injected
 *           require against the page's frozen module table, so they are externals.
 *   types:  tsc emits lib/types/ (the package's .d.ts).
 */
import { build } from 'esbuild'
import { readFileSync } from 'node:fs'
import { rm } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'

const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8'))

/** The page's frozen module table (PLATFORM_MODULES in the harness's web client). */
const PLATFORM_MODULES = [
  'react', 'react/jsx-runtime', 'react-dom', 'react-dom/client', '@deepseek-ai/cordis',
  '@deepseek-ai/dsh-client-store',
  '@deepseek-ai/dsh-client-ui-slots',
  '@deepseek-ai/dsh-client-ui-primitives',
  '@deepseek-ai/dsh-client-ui-dockkit',
]

await rm(new URL('./lib/', import.meta.url), { recursive: true, force: true })

await build({
  entryPoints: ['src/index.ts', 'src/cloud.ts', 'src/relay.ts', 'src/reach.ts', 'src/hub.ts', 'src/profile.ts', 'src/actions.ts', 'src/task.ts', 'src/rooms.ts', 'src/rooms-tools.ts', 'src/connectors.ts', 'src/connectors-tools.ts'],
  outdir: 'lib',
  format: 'esm',
  platform: 'node',
  target: 'node22',
  bundle: true,
  // One copy of hub.ts / profile.ts / relay.ts shared by cloud.js and reach.js, so an
  // `instanceof HubError` in reach sees the class cloud's hub client throws.
  splitting: true,
  chunkNames: 'chunks/[name]-[hash]',
  sourcemap: true,
  packages: 'external',
  logLevel: 'warning',
})

await build({
  entryPoints: { client: 'src/client/index.ts' },
  outdir: 'lib',
  format: 'cjs',
  platform: 'browser',
  target: 'es2022',
  bundle: true,
  minify: false,
  sourcemap: true,
  external: PLATFORM_MODULES,
  jsx: 'automatic',
  define: { 'process.env.NODE_ENV': '"production"', 'process.env.NANOMUSE_VERSION': JSON.stringify(pkg.version) },
  banner: { js: `window.__ModuleLoader__.load({ id: ${JSON.stringify(pkg.name)}, factory: (require) => {\nvar module = { exports: {} }; var exports = module.exports;` },
  footer: { js: 'return module.exports; } });' },
  logLevel: 'warning',
})

const tsc = spawnSync(process.execPath, ['node_modules/typescript/bin/tsc', '-p', 'tsconfig.json', '--noEmit', 'false', '--emitDeclarationOnly', '--declaration', '--outDir', 'lib/types'], { stdio: 'inherit' })
if (tsc.status !== 0) process.exit(tsc.status ?? 1)
console.log('dsh-nanomuse: lib/index.js lib/cloud.js lib/client.js lib/types/')
