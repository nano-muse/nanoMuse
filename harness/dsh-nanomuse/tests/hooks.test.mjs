// The harness's DOM hooks styles.ts leans on (`[data-composer-card]`, `[class*="_toBottom"]`),
// against the dsh packages this plugin installs: the `@deepseek-ai/dsh-client-ui-*` packages and
// the rest of its devDependencies, pinned by pnpm-lock.yaml. None of those hooks is a contract,
// so a dsh release may rename any of them and the rule that leaned on it then matches nothing;
// this test makes `pnpm test` say so. The hooks that live only in `@deepseek-ai/dsh-web-app`,
// which the plugin does not install, are named in WEB_APP_ONLY and are the desktop staging
// step's business (harness/desktop/scripts/check-hooks.mjs, run against the staged app in CI);
// a hook that moves between the two sets shows up here as a difference either way.
import assert from 'node:assert/strict'
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { test } from 'node:test'
import { findIn, hooksOf, setterSpellings } from '../../desktop/scripts/check-hooks.mjs'

const here = fileURLToPath(new URL('.', import.meta.url))
const styles = join(here, '..', 'src', 'client', 'styles.ts')
const scoped = join(here, '..', 'node_modules', '@deepseek-ai')

/** Hooks of the web app's own DOM (the chat flow, the task manager page, the right sidebar), not in any package installed here. */
const WEB_APP_ONLY = [
  'data-approval-scroll',
  'data-chat-running',
  'data-clock',
  'data-detail-tab',
  'data-dockkit-strip',
  'data-dockkit-strip-chrome',
  'data-plugin-panel',
  'data-sidebar-right-expand',
  'data-sidebar-right-panel',
  'data-tool',
  'data-turn-process-inline',
  'data-turn-process-member',
  'data-variant',
  'task-manager-page',
  '_bubble',
  '_centerCol',
  '_endInfo',
  '_frame',
  '_handle',
  '_markdown',
  '_pageHeading',
  '_runningContent',
  '_runningDivider',
  '_timeEnd',
  '_timeStart',
  '_toBottom',
  '_toBottomSlot',
]

test('every hook styles.ts leans on is in the installed dsh packages, set by the bundle itself, or a known web-app hook', { skip: !existsSync(scoped) && 'no @deepseek-ai packages installed' }, () => {
  const { attributes, testIds, stems } = hooksOf(readFileSync(styles, 'utf8'))
  const needles = [...attributes, ...testIds, ...stems]
  assert.ok(needles.length > 40, `the stylesheet reads as leaning on ${needles.length} hooks; the reader may be off`)
  const roots = readdirSync(scoped).map((name) => join(scoped, name))
  const inDsh = findIn(roots, needles)
  const unseen = attributes.filter((a) => !inDsh.has(a))
  const own = findIn([join(here, '..', 'src'), join(here, '..', '..', 'desktop', 'src')], unseen, new Map(unseen.map((a) => [a, setterSpellings(a)])))
  const missing = needles.filter((n) => !inDsh.has(n) && !own.has(n))
  assert.deepEqual(missing, WEB_APP_ONLY, 'a hook the installed dsh packages no longer carry (or one that moved into them): update styles.ts for this dsh, or this list')
  // the bundle's own attributes are the `data-nm-*` family and the root scope; a dsh hook landing here means its setter went missing from dsh
  for (const a of own) assert.ok(/^data-(nm-|nanomuse$|chat-flow-kind$)/.test(a), `${a} is set by the bundle itself but is not one of its own names`)
})
