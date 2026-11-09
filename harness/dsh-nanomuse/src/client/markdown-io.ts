/**
 * Markdown in and out of the document editor: the text becomes HTML the
 * editable shows, and the edited HTML becomes Markdown again when it is saved.
 * The dialect is the one the agent writes and the rooms render (headings,
 * paragraphs, emphasis, code, lists with task boxes, quotes, rules, links,
 * tables); an HTML comment at the top (the file's own note about itself)
 * shows as an italic preface and goes back to a comment.
 */

function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

function inlineHtml(text: string, comments: string[]): string {
  // an inline comment's words ride as a numbered placeholder, so no markup rule can swallow
  // or escape them (a comment inside **bold** keeps its own span), and come back at the end
  const notes: string[] = []
  const plain = text.replace(/\u0000span:(\d+)\u0000/g, (_m, id: string) => {
    notes.push(`<span class="nm-doc-note">${escapeHtml(comments[Number(id)] ?? '')}</span>`)
    return `\u0001${notes.length - 1}\u0001`
  })
  let out = ''
  const re = /(\*\*([^*]+)\*\*|__([^_]+)__|`([^`]+)`|\[([^\]]+)\]\((https?:\/\/[^\s)\u0001]+)\)|\*([^*\n]+)\*|_([^_\n]+)_|<?(https?:\/\/[^\s<>)\u0001]+)>?)/g
  let last = 0
  let match: RegExpExecArray | null
  while ((match = re.exec(plain)) !== null) {
    if (match.index > last) out += escapeHtml(plain.slice(last, match.index))
    if (match[2] !== undefined || match[3] !== undefined) out += `<strong>${escapeHtml(match[2] ?? match[3] ?? '')}</strong>`
    else if (match[4] !== undefined) out += `<code>${escapeHtml(match[4])}</code>`
    else if (match[5] !== undefined && match[6] !== undefined) out += `<a href="${escapeHtml(match[6])}">${escapeHtml(match[5])}</a>`
    else if (match[7] !== undefined || match[8] !== undefined) out += `<em>${escapeHtml(match[7] ?? match[8] ?? '')}</em>`
    else if (match[9] !== undefined) out += `<a href="${escapeHtml(match[9])}">${escapeHtml(match[9])}</a>`
    last = match.index + match[0].length
  }
  if (last < plain.length) out += escapeHtml(plain.slice(last))
  return out.replace(/\u0001(\d+)\u0001/g, (_m, i: string) => notes[Number(i)] ?? '')
}

/** Convert comments outside code; code retains its original bytes and line breaks. */
function commentNotes(source: string, comments: string[]): string {
  const tokens = /^```[^\n]*(?:\n|$)|^>[^\n]*(?:\n|$)|`[^`\n]+`|<!--([\s\S]*?)-->/gm
  let out = ''
  let last = 0
  let match: RegExpExecArray | null
  while ((match = tokens.exec(source)) !== null) {
    out += source.slice(last, match.index)
    if (match[0].startsWith('```')) {
      const closing = /^```[^\n]*/gm
      closing.lastIndex = tokens.lastIndex
      const end = closing.exec(source)
      tokens.lastIndex = end ? end.index + end[0].length : source.length
      out += source.slice(match.index, tokens.lastIndex)
    } else if (match[1] !== undefined) {
      comments.push(match[1].trim().replace(/\n/g, ' '))
      out += `\u0000note:${comments.length - 1}\u0000`
    } else {
      out += match[0]
    }
    last = tokens.lastIndex
  }
  return out + source.slice(last)
}

/** Markdown → HTML for the editable. */
export function mdToHtml(text: string): string {
  return renderMarkdown(text, [])
}

function renderMarkdown(text: string, comments: string[]): string {
  const src = text.replace(/\r\n?/g, '\n')
  // the file's note about itself: comments become prefaces; a comment in the middle of a
  // line is not a note paragraph, and its sentinel must never reach the editable (the
  // autosave would write it into the file), so on any other line it becomes the span form
  const lines = commentNotes(src, comments)
    .split('\n')
    .map((line) =>
      /^\u0000note:[^\u0000]*\u0000\s*$/.test(line)
        ? line
        : line.replace(/\u0000note:([^\u0000]*)\u0000/g, (_m, body: string) => `\u0000span:${body}\u0000`),
    )
  const out: string[] = []
  const paragraph: string[] = []
  const flush = () => {
    if (paragraph.length) out.push(`<p>${inlineHtml(paragraph.join(' '), comments)}</p>`)
    paragraph.length = 0
  }
  let i = 0
  while (i < lines.length) {
    const line = lines[i] ?? ''
    const note = /^\u0000note:([\s\S]*)\u0000\s*$/.exec(line)
    if (note) {
      flush()
      out.push(`<p class="nm-doc-note"><em>${escapeHtml(comments[Number(note[1])] ?? '')}</em></p>`)
      i++
      continue
    }
    if (!line.trim()) {
      flush()
      i++
      continue
    }
    if (/^```/.test(line)) {
      flush()
      const code: string[] = []
      const lang = line.slice(3).trim()
      i++
      while (i < lines.length && !/^```/.test(lines[i] ?? '')) code.push(lines[i++] ?? '')
      i++
      out.push(`<pre${lang ? ` data-lang="${escapeHtml(lang)}"` : ''}><code>${escapeHtml(code.join('\n'))}</code></pre>`)
      continue
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(line)
    if (heading) {
      flush()
      out.push(`<h${heading[1]!.length}>${inlineHtml(heading[2] ?? '', comments)}</h${heading[1]!.length}>`)
      i++
      continue
    }
    if (/^(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      flush()
      out.push('<hr>')
      i++
      continue
    }
    if (/^>\s?/.test(line)) {
      flush()
      const quote: string[] = []
      while (i < lines.length && /^>\s?/.test(lines[i] ?? '')) quote.push((lines[i++] ?? '').replace(/^>\s?/, ''))
      out.push(`<blockquote>${renderMarkdown(quote.join('\n'), comments)}</blockquote>`)
      continue
    }
    if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
      flush()
      const ordered = /^\s*\d+[.)]\s+/.test(line)
      const items: string[] = []
      while (i < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i] ?? '')) {
        let item = (lines[i++] ?? '').replace(/^\s*([-*+]|\d+[.)])\s+/, '')
        while (i < lines.length && /^\s{2,}\S/.test(lines[i] ?? '') && !/^\s*([-*+]|\d+[.)])\s+/.test(lines[i] ?? '')) item += ' ' + (lines[i++] ?? '').trim()
        const task = /^\[([ xX])\]\s+/.exec(item)
        if (task) item = item.slice(task[0].length)
        items.push(`<li${task ? ` data-task="${task[1] === ' ' ? 'todo' : 'done'}"` : ''}>${inlineHtml(item, comments)}</li>`)
      }
      out.push(`<${ordered ? 'ol' : 'ul'}>${items.join('')}</${ordered ? 'ol' : 'ul'}>`)
      continue
    }
    if (/^\|.*\|\s*$/.test(line) && /^\|?\s*:?-{2,}/.test(lines[i + 1] ?? '')) {
      flush()
      const cells = (row: string) => row.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim())
      const head = cells(line)
      i += 2
      const rows: string[][] = []
      while (i < lines.length && /^\|.*\|\s*$/.test(lines[i] ?? '')) rows.push(cells(lines[i++] ?? ''))
      out.push(`<table><thead><tr>${head.map((c) => `<th>${inlineHtml(c, comments)}</th>`).join('')}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${inlineHtml(c, comments)}</td>`).join('')}</tr>`).join('')}</tbody></table>`)
      continue
    }
    paragraph.push(line.trim())
    i++
  }
  flush()
  return out.join('\n')
}

// ---- HTML → Markdown ---------------------------------------------------------------------

function inlineMd(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return (node.textContent ?? '').replace(/\u00a0/g, ' ')
  if (node.nodeType !== Node.ELEMENT_NODE) return ''
  const el = node as HTMLElement
  const tag = el.tagName.toLowerCase()
  const inner = () => Array.from(el.childNodes).map(inlineMd).join('')
  switch (tag) {
    case 'strong':
    case 'b': {
      const text = inner()
      return text.trim() ? `**${text.trim()}**` : text
    }
    case 'em':
    case 'i': {
      const text = inner()
      return text.trim() ? `*${text.trim()}*` : text
    }
    case 'code':
      return `\`${el.textContent ?? ''}\``
    case 'a': {
      const href = el.getAttribute('href') ?? ''
      const text = inner().trim() || href
      return href ? `[${text}](${href})` : text
    }
    case 'br':
      return '\n'
    case 'span':
      // an inline comment's span goes back to the comment it rendered, so the autosave's
      // round trip leaves the file as it found it
      if (el.classList.contains('nm-doc-note')) return `<!-- ${inner().replace(/\s+/g, ' ').trim()} -->`
      return inner()
    case 'u':
    case 's':
    case 'font':
      return inner()
    default:
      return blockMd(el)
  }
}

function listMd(el: HTMLElement, ordered: boolean, depth: number): string {
  const lines: string[] = []
  let n = 1
  for (const child of Array.from(el.children)) {
    if (child.tagName.toLowerCase() !== 'li') continue
    const li = child as HTMLElement
    const nested: string[] = []
    const own: string[] = []
    for (const part of Array.from(li.childNodes)) {
      const tag = part.nodeType === Node.ELEMENT_NODE ? (part as HTMLElement).tagName.toLowerCase() : ''
      if (tag === 'ul' || tag === 'ol') nested.push(listMd(part as HTMLElement, tag === 'ol', depth + 1))
      else own.push(inlineMd(part))
    }
    const task = li.getAttribute('data-task')
    const box = task === 'todo' ? '[ ] ' : task === 'done' ? '[x] ' : ''
    const marker = ordered ? `${n++}. ` : '- '
    lines.push(`${'  '.repeat(depth)}${marker}${box}${own.join('').replace(/\s+/g, ' ').trim()}`)
    for (const block of nested) if (block) lines.push(block)
  }
  return lines.join('\n')
}

function blockMd(el: HTMLElement): string {
  const tag = el.tagName.toLowerCase()
  const inner = () => Array.from(el.childNodes).map(inlineMd).join('')
  switch (tag) {
    case 'h1':
    case 'h2':
    case 'h3':
    case 'h4':
    case 'h5':
    case 'h6':
      return `\n${'#'.repeat(Number(tag[1]))} ${inner().replace(/\s+/g, ' ').trim()}\n`
    case 'p':
    case 'div': {
      if (el.classList.contains('nm-doc-note')) return `\n<!-- ${(el.textContent ?? '').replace(/\s+/g, ' ').trim()} -->\n`
      const text = inner().replace(/[ \t]+/g, ' ').trim()
      return text ? `\n${text}\n` : '\n'
    }
    case 'pre':
      return `\n\`\`\`${el.getAttribute('data-lang') ?? ''}\n${(el.textContent ?? '').replace(/\n$/, '')}\n\`\`\`\n`
    case 'blockquote':
      return `\n${htmlToMd(el.innerHTML).trim().split('\n').map((l) => `> ${l}`).join('\n')}\n`
    case 'ul':
      return `\n${listMd(el, false, 0)}\n`
    case 'ol':
      return `\n${listMd(el, true, 0)}\n`
    case 'hr':
      return '\n---\n'
    case 'table': {
      const rows = Array.from(el.querySelectorAll('tr')).map((tr) => Array.from(tr.children).map((c) => Array.from(c.childNodes).map(inlineMd).join('').replace(/\s+/g, ' ').trim()))
      if (!rows.length) return ''
      const width = Math.max(...rows.map((r) => r.length))
      const line = (cells: string[]) => `| ${Array.from({ length: width }, (_, i) => cells[i] ?? '').join(' | ')} |`
      return `\n${line(rows[0]!)}\n| ${Array.from({ length: width }, () => '---').join(' | ')} |\n${rows.slice(1).map(line).join('\n')}\n`
    }
    case 'thead':
    case 'tbody':
    case 'tr':
    case 'td':
    case 'th':
    case 'li':
      return inner()
    default:
      return inner()
  }
}

/** The editable's HTML back to Markdown, blank lines between blocks, nothing else invented. */
export function htmlToMd(html: string): string {
  const box = document.createElement('div')
  box.innerHTML = html
  const text = Array.from(box.childNodes).map(inlineMd).join('')
  return text.replace(/\n{3,}/g, '\n\n').replace(/^\n+/, '').replace(/\n+$/, '\n')
}
