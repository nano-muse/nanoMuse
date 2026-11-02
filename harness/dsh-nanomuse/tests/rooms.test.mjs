// The rooms' pure helpers: what the agent's final answer parses to, and the first
// title a goal gets before the agent names it.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { goalTitle, parseArray } from '../lib/rooms.js'

test('parseArray takes the last fenced json block', () => {
  const text = 'Here is a draft:\n```json\n[{"title": "draft"}]\n```\nFinal:\n```json\n[{"title": "a"}, {"title": "b"}]\n```\n'
  assert.deepEqual(parseArray(text).map((r) => r.title), ['a', 'b'])
})

test('parseArray falls back to the outermost brackets, and to nothing', () => {
  assert.deepEqual(parseArray('sure: [{"title": "x", "n": 1}] done').map((r) => r.title), ['x'])
  assert.deepEqual(parseArray('no json here'), [])
  assert.deepEqual(parseArray('```json\n{"not": "an array"}\n```'), [])
  assert.deepEqual(parseArray('```json\n[1, "two", {"title": "three"}]\n```').map((r) => r.title), ['three'])
})

test('goalTitle keeps the first clause', () => {
  assert.equal(goalTitle('工作日零点前睡觉；每天 23:00 提醒我，每周日晚上问我这周睡得怎么样。'), '工作日零点前睡觉')
  assert.equal(goalTitle('Save ¥20,000 by December; track it monthly and tell me when I drift.'), 'Save ¥20,000 by December')
  assert.equal(goalTitle('Run a 10k'), 'Run a 10k')
  assert.equal(goalTitle('Hi, call my parents every Sunday'), 'Hi, call my parents every Sunday'.slice(0, 40))
  assert.equal(goalTitle('x'.repeat(80)).length, 40)
})

test('zip writes an archive Python can read back', async () => {
  const { zip, crc32 } = await import('../lib/rooms.js')
  const { writeFile, mkdtemp, rm } = await import('node:fs/promises')
  const { tmpdir } = await import('node:os')
  const { join } = await import('node:path')
  const { spawnSync } = await import('node:child_process')
  assert.equal(crc32(Buffer.from('')), 0)
  assert.equal(crc32(Buffer.from('123456789')), 0xcbf43926)
  const dir = await mkdtemp(join(tmpdir(), 'nm-zip-'))
  const file = join(dir, 'x.zip')
  const big = Buffer.alloc(5000, 'a')
  await writeFile(file, zip([
    { name: 'nanomuse/rooms.json', data: Buffer.from('{"goals":[]}'), at: new Date(2026, 9, 3, 12, 30, 10) },
    { name: '构件/读我.txt', data: big, at: new Date() },
  ]))
  const py = spawnSync('python3', ['-c', `import zipfile,sys; z=zipfile.ZipFile(sys.argv[1]); print(z.testzip()); print(','.join(i.filename for i in z.infolist())); print(len(z.read('构件/读我.txt')))`, file], { encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } })
  await rm(dir, { recursive: true, force: true })
  if (py.status !== 0) return // no python here; the crc checks above still ran
  assert.equal(py.stdout.trim().split(/\r?\n/)[0], 'None')
  assert.equal(py.stdout.trim().split(/\r?\n/)[1], 'nanomuse/rooms.json,构件/读我.txt')
  assert.equal(py.stdout.trim().split(/\r?\n/)[2], '5000')
})

test('writeZipFile streams an archive Python reads back, one entry at a time', async () => {
  const { writeZipFile } = await import('../lib/rooms.js')
  const { writeFile, mkdtemp, rm } = await import('node:fs/promises')
  const { tmpdir } = await import('node:os')
  const { join } = await import('node:path')
  const { spawnSync } = await import('node:child_process')
  const dir = await mkdtemp(join(tmpdir(), 'nm-zipfile-'))
  const file = join(dir, 'x.zip')
  const source = join(dir, 'big.bin')
  await writeFile(source, Buffer.alloc(5000, 'a'))
  const entries = [
    { name: 'nanomuse/rooms.json', data: Buffer.from('{"goals":[]}'), at: new Date(2026, 9, 3, 12, 30, 10) },
    { name: 'sessions/big.bin', path: source, at: new Date() },
    { name: 'sessions/gone.bin', path: join(dir, 'gone.bin'), at: new Date() }, // vanished since the scan
  ]
  await writeZipFile(file, entries)
  await writeZipFile(file, entries) // a second export in the same second replaces the first
  const py = spawnSync('python3', ['-c', `import zipfile,sys; z=zipfile.ZipFile(sys.argv[1]); print(z.testzip()); print(','.join(i.filename for i in z.infolist())); print(len(z.read('sessions/big.bin')))`, file], { encoding: 'utf8' })
  await rm(dir, { recursive: true, force: true })
  if (py.status !== 0) return // no python here
  assert.deepEqual(py.stdout.trim().split(/\r?\n/), ['None', 'nanomuse/rooms.json,sessions/big.bin', '5000']) // Python prints \r\n on Windows
})

test('the export leaves links, loops and oversized files out instead of following them', async (t) => {
  const { EXPORT_MAX_FILE_BYTES, scanExportRoot } = await import('../lib/rooms.js')
  const { mkdir, mkdtemp, rm, symlink, truncate, writeFile } = await import('node:fs/promises')
  const { tmpdir } = await import('node:os')
  const { join } = await import('node:path')
  if (process.platform === 'win32') return t.skip('symlink creation needs elevated rights on Windows')
  const dir = await mkdtemp(join(tmpdir(), 'nm-export-links-'))
  try {
    await mkdir(join(dir, 'root', 'faces'), { recursive: true })
    await writeFile(join(dir, 'root', 'profile.json'), '{}')
    await writeFile(join(dir, 'root', 'faces', 'calm.png'), 'png')
    await writeFile(join(dir, 'outside'), 'secret')
    await symlink('.', join(dir, 'root', 'loop'))
    await symlink(join(dir, 'outside'), join(dir, 'root', 'outside'))
    await writeFile(join(dir, 'root', 'huge.mp4'), '')
    await truncate(join(dir, 'root', 'huge.mp4'), EXPORT_MAX_FILE_BYTES + 1)
    const budget = { files: 0, bytes: 0 }
    const names = (await scanExportRoot(join(dir, 'root'), 'nanomuse/', budget)).map((e) => e.name).sort()
    assert.deepEqual(names, ['nanomuse/faces/calm.png', 'nanomuse/profile.json'])
    assert.deepEqual(budget, { files: 2, bytes: 5 })
    // a root that is not there, or is a link, is nothing
    assert.deepEqual(await scanExportRoot(join(dir, 'missing'), 'sessions/', budget), [])
    await symlink(join(dir, 'root'), join(dir, 'linked-root'))
    assert.deepEqual(await scanExportRoot(join(dir, 'linked-root'), 'sessions/', budget), [])
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
})

test('an export past what one zip holds fails instead of writing a zip no tool opens', async () => {
  const { EXPORT_MAX_BYTES, EXPORT_MAX_FILES, scanExportRoot } = await import('../lib/rooms.js')
  const { mkdir, mkdtemp, rm, writeFile } = await import('node:fs/promises')
  const { tmpdir } = await import('node:os')
  const { join } = await import('node:path')
  const dir = await mkdtemp(join(tmpdir(), 'nm-export-limits-'))
  const root = join(dir, 'root')
  try {
    await mkdir(root)
    await writeFile(join(root, 'one'), 'x')
    await assert.rejects(scanExportRoot(root, 'x/', { files: EXPORT_MAX_FILES, bytes: 0 }), /more than/)
    await assert.rejects(scanExportRoot(root, 'x/', { files: 0, bytes: EXPORT_MAX_BYTES }), /over/)
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
})

test('exported proxy settings remove URL userinfo', async () => {
  const { redactProxyUserinfo } = await import('../lib/rooms.js')
  const redacted = JSON.parse(redactProxyUserinfo(Buffer.from(JSON.stringify({
    proxy: 'http://alice:secret@proxy.example:8080',
    menuBar: true,
  }))).toString())
  assert.equal(redacted.proxy, 'http://proxy.example:8080')
  assert.equal(redacted.menuBar, true)
})

test('a file name a person typed or brought in becomes one safe path segment (#689)', async () => {
  const { safeStem } = await import('../lib/rooms.js')
  assert.equal(safeStem('notes.md'), 'notes')
  assert.equal(safeStem('C:\\Users\\me\\Reading list.markdown'), 'Reading list')
  assert.equal(safeStem('../../etc/passwd.txt'), 'passwd')
  assert.equal(safeStem('what: "a-b" | c?*.txt'), 'what a-b c')
  assert.equal(safeStem('会议纪要 2026-10.md'), '会议纪要 2026-10')
  assert.equal(safeStem('trailing dots... .md'), 'trailing dots')
  assert.equal(safeStem('.md'), '')
  assert.equal(safeStem('   '), '')
  assert.equal(safeStem(`${'x'.repeat(200)}.md`).length, 80)
})

test('a new file takes the next free number instead of overwriting (#689)', async () => {
  const { freePath } = await import('../lib/rooms.js')
  const { mkdtemp, rm, writeFile } = await import('node:fs/promises')
  const { tmpdir } = await import('node:os')
  const { basename, join } = await import('node:path')
  const dir = await mkdtemp(join(tmpdir(), 'nm-library-'))
  try {
    assert.equal(basename(await freePath(dir, 'Untitled', '.md')), 'Untitled.md')
    await writeFile(join(dir, 'Untitled.md'), '')
    assert.equal(basename(await freePath(dir, 'Untitled', '.md')), 'Untitled (2).md')
    await writeFile(join(dir, 'Untitled (2).md'), '')
    assert.equal(basename(await freePath(dir, 'Untitled', '.md')), 'Untitled (3).md')
    assert.equal(basename(await freePath(dir, 'Untitled', '.txt')), 'Untitled.txt')
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
})

test('memory dates follow fixed local calendar boundaries east and west of UTC', async () => {
  const { execFileSync } = await import('node:child_process')
  for (const [zone, at, expected] of [
    ['Asia/Shanghai', '2026-01-01T16:30:00Z', '2026-01-02'],
    ['America/Los_Angeles', '2026-01-01T00:30:00Z', '2025-12-31'],
    ['UTC', '2026-01-01T00:30:00Z', '2026-01-01'],
  ]) {
    const script = `import { memoryDoc } from ${JSON.stringify(new URL('../lib/rooms.js', import.meta.url).href)};
      console.log(memoryDoc([{ source: 'agent', at: Date.parse(${JSON.stringify(at)}), text: 'boundary memory' }], false));`
    const doc = execFileSync(process.execPath, ['--input-type=module', '-e', script], {
      env: { ...process.env, TZ: zone }, encoding: 'utf8',
    })
    assert.ok(doc.includes(`(${expected})`), `${zone}: ${doc}`)
  }
})
