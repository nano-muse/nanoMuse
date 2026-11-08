import { after, before, test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'
import { build } from 'esbuild'

const here = fileURLToPath(new URL('.', import.meta.url))
let directory
let io

before(async () => {
  directory = await mkdtemp(join(tmpdir(), 'nm-markdown-io-'))
  const output = join(directory, 'markdown-io.mjs')
  await build({
    entryPoints: [join(here, '..', 'src', 'client', 'markdown-io.ts')],
    outfile: output,
    bundle: true,
    platform: 'node',
    format: 'esm',
    logLevel: 'silent',
  })
  io = await import(pathToFileURL(output).href)
})

after(async () => {
  await rm(directory, { recursive: true, force: true })
})

/**
 * A document good enough for htmlToMd over the shapes mdToHtml emits: p (with or without a
 * class), em, span with a class, pre>code, and text between them. Entities decode the way a
 * real DOM would. Anything outside that grammar throws, so a drift in the editor dialect
 * fails the test instead of passing it vacuously.
 */
function withDocument(run) {
  const decode = (text) => text.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&amp;/g, '&')
  const textNode = (data) => ({ nodeType: 3, textContent: data })
  const element = (tag, className, nodes) => ({
    nodeType: 1,
    tagName: tag.toUpperCase(),
    childNodes: nodes,
    children: nodes.filter((n) => n.nodeType === 1),
    get textContent() {
      return this.childNodes.map((n) => (n.nodeType === 3 ? n.textContent : n.textContent)).join('')
    },
    getAttribute(name) {
      return name === 'class' && className ? className : name === 'data-lang' ? this.dataset?.lang ?? null : null
    },
    get classList() {
      return { contains: (name) => className === name }
    },
    querySelectorAll() {
      return []
    },
  })
  const parse = (html) => {
    const nodes = []
    const re = /<(span|pre|code|em|p)(?: class="([^"]*)")?[^>]*>|<\/(span|pre|code|em|p)>|([^<]+)/g
    const stack = [{ childNodes: nodes }]
    let match
    while ((match = re.exec(html)) !== null) {
      if (match[4] !== undefined && match[4].length) stack.at(-1).childNodes.push(textNode(decode(match[4])))
      else if (match[1]) stack.push({ childNodes: [], tag: match[1], className: match[2] ?? '' })
      else if (match[3]) {
        const top = stack.pop()
        stack.at(-1).childNodes.push(element(top.tag, top.className, top.childNodes))
      }
    }
    if (stack.length !== 1) throw new Error(`test shim cannot parse: ${html}`)
    return nodes
  }
  const previousDocument = Object.getOwnPropertyDescriptor(globalThis, 'document')
  const previousNode = Object.getOwnPropertyDescriptor(globalThis, 'Node')
  Object.defineProperty(globalThis, 'Node', { configurable: true, value: { TEXT_NODE: 3, ELEMENT_NODE: 1 } })
  Object.defineProperty(globalThis, 'document', {
    configurable: true,
    value: {
      createElement: () => {
        const box = { childNodes: [] }
        Object.defineProperty(box, 'innerHTML', {
          configurable: true,
          set(html) {
            box.childNodes = parse(html)
          },
        })
        return box
      },
    },
  })
  try {
    return run()
  } finally {
    if (previousDocument) Object.defineProperty(globalThis, 'document', previousDocument)
    else delete globalThis.document
    if (previousNode) Object.defineProperty(globalThis, 'Node', previousNode)
    else delete globalThis.Node
  }
}

test('a whole-line comment stays the preface note, and the round trip keeps it a comment', () => {
  const html = io.mdToHtml('<!-- the file note -->\n\nbody text')
  assert.ok(!html.includes('\u0000'), 'no sentinel may reach the editable')
  assert.equal(html, '<p class="nm-doc-note"><em>the file note</em></p>\n<p>body text</p>')
  const back = withDocument(() => io.htmlToMd(html))
  assert.equal(back, '<!-- the file note -->\n\nbody text\n')
})

test('an inline comment renders as words in the line, without any sentinel', () => {
  const html = io.mdToHtml('see <!-- todo --> here')
  assert.ok(!html.includes('\u0000'), 'the sentinel must not leak into the rendered text')
  assert.equal(html, '<p>see <span class="nm-doc-note">todo</span> here</p>')
})

test('an inline comment survives the round trip the autosave makes', () => {
  // DocEditor saves htmlToMd(mdToHtml(file)) nine hundred milliseconds after any edit;
  // a comment in the middle of a line must still be a comment when that lands
  for (const [source, roundTripped] of [
    ['see <!-- todo --> here', 'see <!-- todo --> here\n'],
    ['costs <!-- approx --> 5 dollars, not 6', 'costs <!-- approx --> 5 dollars, not 6\n'],
    ['<!---->', '<!--  -->\n'],
    ['<!-- todo --><!-- twice -->', '<!-- todo --><!-- twice -->\n'],
  ]) {
    const html = io.mdToHtml(source)
    assert.ok(!html.includes('\u0000'), source)
    assert.equal(withDocument(() => io.htmlToMd(html)), roundTripped, source)
  }
})

test('a comment inside a code fence stays source text, sentinel-free', () => {
  const html = io.mdToHtml('```\nsee <!-- todo --> here\n```')
  assert.ok(!html.includes('\u0000'), 'the sentinel must not reach the code block')
  assert.equal(html, '<pre><code>see &lt;!-- todo --&gt; here</code></pre>')
  const back = withDocument(() => io.htmlToMd(html))
  assert.equal(back, '```\nsee <!-- todo --> here\n```\n')
})

test('plain text and its marks keep round-tripping unchanged', () => {
  for (const source of ['plain words', 'two\n\nparagraphs', 'a < b & "c"']) {
    const html = io.mdToHtml(source)
    assert.ok(!html.includes('\u0000'), source)
    assert.equal(withDocument(() => io.htmlToMd(html)), source + '\n', source)
  }
})
