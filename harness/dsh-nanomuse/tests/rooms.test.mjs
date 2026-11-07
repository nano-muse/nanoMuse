// The rooms' pure helpers: what the agent's final answer parses to, and the first
// title a goal gets before the agent names it.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import Rooms, { goalTitle, parseArray } from '../lib/rooms.js'

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

function memoryImportFixture(count = 0) {
  const self = {
    store: { memory: Array.from({ length: count }, (_, i) => ({ id: `old-${i}`, at: 1, text: `Existing fact ${i}`, source: 'person' })) },
    saved: [],
    async save() { this.saved.push(structuredClone(this.store.memory)) },
  }
  return { self, run: (text) => Rooms.prototype.importMemory.call(self, text) }
}

test('memory import rejects every over-limit batch without changing existing entries', async () => {
  for (const [count, text, code] of [
    [1, `Valid first line\n${'x'.repeat(401)}`, 'memory_import_length'],
    [1, Array.from({ length: 201 }, (_, i) => `New fact ${i}`).join('\n'), 'memory_import_lines'],
    [399, 'New fact one\nNew fact two', 'memory_import_capacity'],
    [400, 'Existing fact 0\nA new fact', 'memory_import_capacity'],
  ]) {
    const { self, run } = memoryImportFixture(count)
    const before = structuredClone(self.store.memory)
    await assert.rejects(run(text), { code })
    assert.deepEqual(self.store.memory, before)
    assert.deepEqual(self.saved, [])
  }
})

test('memory import counts only unique additions and preserves duplicates at capacity', async () => {
  const { self, run } = memoryImportFixture(399)
  const before = structuredClone(self.store.memory)
  assert.equal(await run('- Existing fact 0\r\n* New fact\n2. New   fact\n'), 1)
  assert.deepEqual(self.store.memory.slice(0, 399), before)
  assert.equal(self.store.memory[399].text, 'New fact')
  assert.equal(self.store.memory[399].source, 'import')
  assert.equal(self.saved.length, 1)
  assert.equal(self.saved[0].length, 400)
  assert.equal(await run('New fact\nExisting fact 0'), 0)
  assert.equal(self.saved.length, 2)
})

test('memory import accepts a full batch at the documented limits and one-character facts', async () => {
  const { self, run } = memoryImportFixture()
  const lines = Array.from({ length: 200 }, (_, i) => `${i}: ${'字'.repeat(400)}`.slice(0, 400))
  assert.equal(await run(lines.join('\n')), 200)
  assert.deepEqual(self.store.memory.map((item) => item.text), lines)
  assert.equal(await run('甲\r乙\n\n'), 2)
  assert.deepEqual(self.store.memory.slice(-2).map((item) => item.text), ['甲', '乙'])
})

test('memory import distinguishes list markers from negative numbers and decimal facts', async () => {
  const { self, run } = memoryImportFixture()
  assert.equal(await run('-40 degrees\n1.23 units\n- Listed fact\n1. Another fact'), 4)
  assert.deepEqual(self.store.memory.map((item) => item.text), ['-40 degrees', '1.23 units', 'Listed fact', 'Another fact'])
})

test('memory import HTTP route accepts a full UTF-8 batch and refuses oversized bodies unchanged', async () => {
  const { Readable } = await import('node:stream')
  const rooms = new Rooms({ reflect: { provide() {} }, logger: { warn() {} } })
  let saved = 0
  rooms.save = async () => { saved++ }
  const post = async (text) => {
    const req = Readable.from([Buffer.from(JSON.stringify({ text }))])
    req.method = 'POST'
    req.url = '/nanomuse/rooms/memory/import'
    req.headers = {}
    const res = { status: 0, body: undefined, writeHead(status) { this.status = status; return this }, end(body) { this.body = JSON.parse(body); return this } }
    await rooms.handle(req, res)
    return res
  }
  const text = Array.from({ length: 200 }, (_, i) => `${i}: ${'字'.repeat(400)}`.slice(0, 400)).join('\n')
  const accepted = await post(text)
  assert.equal(accepted.status, 200)
  assert.deepEqual(accepted.body, { added: 200 })
  const before = structuredClone(rooms.memory)
  for (const [text, code, status] of [
    ['Valid new line\n' + 'x'.repeat(401), 'memory_import_length', 400],
    ['x'.repeat(512 * 1024), 'too_large', 413],
  ]) {
    const rejected = await post(text)
    assert.equal(rejected.status, status)
    assert.equal(rejected.body.error.code, code)
    assert.deepEqual(rooms.memory, before)
  }
  assert.equal(saved, 1)
})

test('failed disk writes are reported and the same import can be retried without losing concurrent memories', async () => {
  const { execFileSync } = await import('node:child_process')
  const { mkdtemp, rm } = await import('node:fs/promises')
  const { tmpdir } = await import('node:os')
  const { join } = await import('node:path')
  const home = await mkdtemp(join(tmpdir(), 'nm-memory-write-'))
  try {
    const script = `
      import Rooms from ${JSON.stringify(new URL('../lib/rooms.js', import.meta.url).href)};
      import { mkdir, readFile, rm } from 'node:fs/promises';
      import { join } from 'node:path';
      const rooms = new Rooms({ reflect: { provide() {} }, logger: { warn() {} } });
      rooms.broadcast = () => {};
      const path = join(process.env.DSH_HOME, 'nanomuse', 'rooms.json');
      await mkdir(path, { recursive: true });
      const failed = rooms.importMemory('Imported fact').then(() => 'unexpected_success', error => error.code);
      await rooms.remember('Concurrent fact', 'person');
      const code = await failed;
      await rm(path, { recursive: true });
      const added = await rooms.importMemory('Imported fact');
      const saved = JSON.parse(await readFile(path, 'utf8')).memory.map(item => item.text);
      console.log(JSON.stringify({ code, added, saved }));
    `
    const result = JSON.parse(execFileSync(process.execPath, ['--input-type=module', '-e', script], {
      env: { ...process.env, DSH_HOME: home }, encoding: 'utf8',
    }))
    assert.deepEqual(result, { code: 'memory_import_save', added: 0, saved: ['Imported fact', 'Concurrent fact'] })
  } finally {
    await rm(home, { recursive: true, force: true })
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


test('cleared chat records are removed and cannot be read or recreated by late events', async () => {
  let saved
  const ctx = { nanomuseCloud: { isClearedSession: id => id === 'old' } }
  const self = { ctx, store: { activity: [{ sessionId: 'old', request: 'old words' }, { sessionId: 'kept', request: 'kept words' }] }, save: async function () { saved = structuredClone(this.store) } }
  assert.equal(Rooms.prototype.activityOf.call(self, 'old'), undefined)
  assert.equal(Rooms.prototype.activityOf.call(self, 'kept').request, 'kept words')
  await Rooms.prototype.clearActivity.call(self, ['old'])
  Rooms.prototype.trackActivity.call(self, { id: 'old' }, { type: 'turn/start' })
  assert.deepEqual(saved.activity.map(row => row.sessionId), ['kept'])
  assert.deepEqual(self.store.activity.map(row => row.sessionId), ['kept'])
})
