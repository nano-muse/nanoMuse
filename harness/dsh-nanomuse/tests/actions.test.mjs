// This computer's hands for the other devices: the shapes and limits the runtime's
// `nanomuse/hub/actions.py` has, so a phone cannot tell the two apart.
import assert from 'node:assert/strict'
import { access, mkdtemp, readFile, readdir, realpath, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'
import { brief, expand, fileGet, filePut, files, open, pngSize, run, screen, shell, windowsOpener } from '../lib/actions.js'

const posix = process.platform !== 'win32'

async function scratch(work) {
  // realpath: macOS hands out /var/folders/… for a directory that is really under /private/var, and `pwd` says so
  const dir = await realpath(await mkdtemp(join(tmpdir(), 'nanomuse-actions-')))
  try {
    return await work(dir)
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}

test('expand: ~, env vars and relative paths land under home', () => {
  const home = posix ? '/home/someone' : 'C:\\Users\\someone'
  assert.equal(expand('~', home), home)
  assert.equal(expand(undefined, home), home)
  assert.ok(expand('~/Desktop', home).endsWith('Desktop'))
  assert.ok(expand('notes', home).startsWith(home))
  process.env.NANOMUSE_TEST_DIR = home
  assert.equal(expand('$NANOMUSE_TEST_DIR', home), home)
  assert.equal(expand('%NANOMUSE_TEST_DIR%', home), home)
  delete process.env.NANOMUSE_TEST_DIR
})

test('shell: exit code, output, cwd and a timeout that kills the command', async () => {
  // POSIX shells chain with ';' and end lines bare; cmd chains with '&', ends every line with '\r', and its echo keeps the word cleanest with '&' tight against it
  const ok = await shell({ command: posix ? 'echo hello; echo oops >&2; exit 3' : 'echo hello&echo oops>&2&exit 3' })
  assert.equal(ok.exit_code, 3)
  assert.equal(ok.stdout, posix ? 'hello\n' : 'hello\r\n')
  assert.equal(ok.stderr, posix ? 'oops\n' : 'oops\r\n')
  assert.equal(ok.timed_out, false)
  assert.ok(typeof ok.duration_ms === 'number')

  await scratch(async (dir) => {
    const here = await shell({ command: posix ? 'pwd' : 'cd', cwd: dir })
    const printed = here.stdout.trim()
    // Windows paths are case-insensitive, and cmd prints the drive the way it was given
    if (posix) assert.equal(printed, dir)
    else assert.equal(printed.toLowerCase(), dir.toLowerCase())
  })

  const slow = await shell({ command: posix ? 'sleep 5; echo late' : 'ping -n 6 127.0.0.1 >nul&echo late', timeout: 1 })
  assert.equal(slow.timed_out, true)
  assert.equal(slow.exit_code, 124)
  assert.ok(slow.duration_ms < 4000, `took ${slow.duration_ms}ms`)

  await assert.rejects(shell({ command: '   ' }), (e) => e.code === 'usage')
})

test('shell bounds tens of megabytes while receiving them and keeps both ends', async () => {
  // POSIX takes the payload inline; on Windows the command crosses cmd.exe, whose handling of a quoted inline script does not survive the spawn, so the same payload is written to a file beside the run and started bare from the cwd
  await scratch(async (dir) => {
    if (!posix) {
      await writeFile(join(dir, 'payload.js'), "process.stdout.write('HEAD'+ 'x'.repeat(30*1024*1024) +'TAIL'); process.stderr.write('ERRHEAD'+ 'y'.repeat(24*1024*1024) +'ERRTAIL')")
    }
    const command = posix
      ? `${JSON.stringify(process.execPath)} -e "process.stdout.write('HEAD'+ 'x'.repeat(30*1024*1024) +'TAIL'); process.stderr.write('ERRHEAD'+ 'y'.repeat(24*1024*1024) +'ERRTAIL')"`
      : 'node payload.js'
    const result = await shell({ command, timeout: 20, cwd: posix ? undefined : dir })
    assert.equal(result.exit_code, 0)
    assert.ok(result.stdout.startsWith('HEAD'))
    assert.ok(result.stdout.endsWith('TAIL'))
    assert.ok(result.stderr.startsWith('ERRHEAD'))
    assert.ok(result.stderr.endsWith('ERRTAIL'))
    assert.match(result.stdout, /bytes not shown/)
    assert.ok(result.stdout.length < 220_000)
    assert.ok(result.stderr.length < 220_000)
  })
})

test('shell: a command with quotes in it survives the Windows shell', { skip: posix }, async () => {
  // the interpreter's own path is the everyday quoted-with-spaces command: "C:\Program Files\...\node.exe"
  const command = `${JSON.stringify(process.execPath)} -e "console.log('quoted ok')"`
  const ok = await shell({ command, timeout: 30 })
  assert.equal(ok.exit_code, 0)
  assert.equal(ok.stdout.trim(), 'quoted ok')

  // an argument in quotes next to it, the shape every spaced path arrives in
  const withArg = `${JSON.stringify(process.execPath)} -e "console.log(process.argv[1])" "${JSON.stringify('a value with spaces').slice(1, -1)}"`
  const passed = await shell({ command: withArg, timeout: 30 })
  assert.equal(passed.exit_code, 0)
  assert.equal(passed.stdout.trim(), 'a value with spaces')
})

test('shell timeout kills the descendant process tree', async () => {
  await scratch(async (dir) => {
    const marker = join(dir, 'leaked')
    // POSIX backgrounds a subshell that writes the marker after three seconds; Windows starts a bare node grandchild (start /b) on the same errand - either way the shell dies at the timeout and the marker must never land
    let result
    if (posix) {
      result = await shell({ command: `(sleep 3; printf leaked > ${JSON.stringify(marker)}) & wait`, timeout: 1 })
    } else {
      await writeFile(join(dir, 'grandchild.js'), "setTimeout(() => { require('node:fs').writeFileSync('leaked', 'x'); process.exit(0) }, 3000)")
      result = await shell({ command: 'start /b node grandchild.js&ping -n 6 127.0.0.1 >nul', timeout: 1, cwd: dir })
    }
    assert.equal(result.timed_out, true)
    await new Promise((resolve) => setTimeout(resolve, 2500))
    await assert.rejects(access(marker))
  })
})

test('files, file.get and file.put: listing, limits and the force rule', async () => {
  await scratch(async (dir) => {
    await writeFile(join(dir, 'b.txt'), 'bee')
    await writeFile(join(dir, 'a.json'), '{}')
    await filePut({ path: join(dir, 'sub', 'c.bin'), data: Buffer.from('cee').toString('base64') })

    const listing = await files({ path: dir })
    assert.equal(listing.path, dir)
    assert.deepEqual(listing.entries.map((e) => [e.name, e.type]), [['sub', 'dir'], ['a.json', 'file'], ['b.txt', 'file']])
    assert.equal(listing.entries[2].size, 3)

    const one = await files({ path: join(dir, 'b.txt') })
    assert.equal(one.entries.length, 1)
    assert.equal(one.entries[0].name, 'b.txt')

    await assert.rejects(files({ path: join(dir, 'missing') }), (e) => e.code === 'not_found')

    const got = await fileGet({ path: join(dir, 'a.json') })
    assert.equal(got.name, 'a.json')
    assert.equal(got.mime, 'application/json')
    assert.equal(got.bytes, 2)
    assert.equal(Buffer.from(got.data, 'base64').toString(), '{}')
    await assert.rejects(fileGet({ path: dir }), (e) => e.code === 'not_found')

    await assert.rejects(filePut({ path: join(dir, 'b.txt'), data: '' }), (e) => e.code === 'exists')
    await assert.rejects(filePut({ path: dir, data: '' }), (e) => e.code === 'is_dir')
    const replaced = await filePut({ path: join(dir, 'b.txt'), data: Buffer.from('new').toString('base64'), force: true })
    assert.equal(replaced.bytes, 3)
    assert.equal(await readFile(join(dir, 'b.txt'), 'utf8'), 'new')
    await assert.rejects(filePut({ data: '' }), (e) => e.code === 'usage')

    const oversized = Buffer.alloc(8 * 1024 * 1024 + 1).toString('base64')
    const tooLarge = join(dir, 'too-large.bin')
    await assert.rejects(filePut({ path: tooLarge, data: oversized }), (e) => e.code === 'too_large')
    await assert.rejects(access(tooLarge))
    assert.equal((await readdir(dir)).some((name) => name.endsWith('.nanomuse-part')), false)
  })
})

test('open: a URL goes to the platform opener, a missing path is refused', async () => {
  const calls = []
  const fake = { platform: 'linux', env: {}, run: async (file, args) => { calls.push([file, ...args]); return 0 } }
  const opened = await open({ url: 'https://nanomuse.cn/' }, fake)
  assert.deepEqual(opened, { ok: true, url: 'https://nanomuse.cn/' })
  assert.deepEqual(calls, [['xdg-open', 'https://nanomuse.cn/']])

  const mac = { platform: 'darwin', env: {}, run: async (file) => (file === 'open' ? 0 : 1) }
  assert.equal((await open({ url: 'https://nanomuse.cn/' }, mac)).ok, true)

  const broken = { platform: 'linux', env: {}, run: async () => { throw new Error('no xdg-open') } }
  assert.equal((await open({ url: 'https://nanomuse.cn/' }, broken)).ok, false)

  await assert.rejects(open({ url: '' }, fake), (e) => e.code === 'usage')
  await assert.rejects(open({ url: '/definitely/not/here/nanomuse' }, fake), (e) => e.code === 'not_found')

  // Windows: PowerShell's Start-Process with the target as an encoded literal, so cmd never reads %NAME% or & in a URL
  const winCalls = []
  const win = { platform: 'win32', env: {}, run: async (file, args) => { winCalls.push([file, ...args]); return 0 } }
  const url = "https://example.invalid/?q=%USERNAME%&x='1'"
  assert.equal((await open({ url }, win)).ok, true)
  const [file, ...args] = winCalls[0]
  assert.equal(file, 'powershell.exe')
  assert.ok(args.includes('-NonInteractive') && args.includes('-EncodedCommand'))
  const script = Buffer.from(args[args.length - 1], 'base64').toString('utf16le')
  assert.equal(script, "Start-Process -FilePath 'https://example.invalid/?q=%USERNAME%&x=''1'''")
  const local = windowsOpener("C:\\Users\\me\\it's.pdf")
  assert.equal(Buffer.from(local.args[local.args.length - 1], 'base64').toString('utf16le'), "Start-Process -FilePath 'C:\\Users\\me\\it''s.pdf'")
})

test('screen: no display means no_screen; a tool that writes a PNG is read back', async () => {
  await assert.rejects(screen({ platform: 'linux', env: {}, run: async () => 0 }), (e) => e.code === 'no_screen')

  const png = Buffer.alloc(33)
  png.write('\x89PNG\r\n\x1a\n', 0, 'latin1')
  png.writeUInt32BE(13, 8)
  png.write('IHDR', 12, 'latin1')
  png.writeUInt32BE(640, 16)
  png.writeUInt32BE(480, 20)
  assert.deepEqual(pngSize(png), { width: 640, height: 480 })
  assert.deepEqual(pngSize(Buffer.from('nope')), { width: 0, height: 0 })

  const tried = []
  const fake = {
    platform: 'linux',
    env: { DISPLAY: ':0' },
    run: async (file, args) => {
      tried.push(file)
      if (file !== 'grim') return 1
      await writeFile(args[args.length - 1], png)
      return 0
    },
  }
  const shot = await screen(fake)
  assert.equal(shot.mime, 'image/png')
  assert.equal(shot.width, 640)
  assert.equal(shot.height, 480)
  assert.equal(shot.bytes, 33)
  assert.equal(Buffer.from(shot.data, 'base64').length, 33)
  assert.deepEqual(tried, ['gnome-screenshot', 'spectacle', 'grim'])
})

test('run dispatches by hub name; brief says what was asked', async () => {
  await scratch(async (dir) => {
    const listing = await run('files', { path: dir })
    assert.equal(listing.path, dir)
  })
  assert.equal(brief('shell', { command: '  ls   -la\n' }), 'ls -la')
  assert.equal(brief('files', {}), '~')
  assert.equal(brief('open', { url: 'https://nanomuse.cn/' }), 'https://nanomuse.cn/')
  assert.equal(brief('screen', {}), '')
  assert.equal(brief('shell', { command: 'x'.repeat(100) }).length, 80)
})
