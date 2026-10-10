/**
 * The document editor, the full main column the Muse desktop gives a file
 * opened from the identity cards or the rail: a bar with the sidebar toggle,
 * the file's name, the formatting buttons (B, I, H1–H3, lists), a ⋯ menu
 * (view source, copy, download, download as PDF, delete / reset) and ×; under
 * it the document itself, written in place. IDENTITY.md and SOUL.md are the
 * agent's own and go to the host's rooms store (the prompt reads them);
 * MEMORY.md writes back as memory lines; a Library file writes to disk.
 */
import { failureText } from './api.ts'
import { createElement as h, useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import type { Translate } from './api.ts'
import { IconClose, IconCode, IconCopy, IconDownload, IconLayout, IconRefresh, IconTrash } from './icons.tsx'
import { htmlToMd, mdToHtml } from './markdown-io.ts'
import { fileUrl, roomsCall, useRooms, type DocName, type DocText } from './rooms.ts'
import { MoreButton, type MenuChoice } from './ui.tsx'
import { useWin, win, type OpenDoc } from './win.ts'

const SAVE_AFTER_MS = 900

export interface DocEditorProps {
  t: Translate
  toggleSidebar(): void
}

const OWN_NAMES: Record<DocName, string> = { identity: 'IDENTITY.md', soul: 'SOUL.md', memory: 'MEMORY.md' }

export function makeDocEditor(t: Translate, toggleSidebar: () => void) {
  return function DocEditor(): ReactNode {
    const doc = useWin().editor
    if (!doc) return null
    const key = doc.kind === 'own' ? doc.doc : doc.id
    return h(Editor, { key, t, toggleSidebar, doc })
  }
}

function Editor({ t, toggleSidebar, doc }: DocEditorProps & { doc: OpenDoc }): ReactNode {
  const rooms = useRooms()
  const [text, setText] = useState<string | null>(null)
  const [source, setSource] = useState(false)
  const [error, setError] = useState<string | undefined>()
  const [saved, setSaved] = useState<'idle' | 'dirty' | 'saving' | 'saved'>('idle')
  const body = useRef<HTMLDivElement>(null)
  const timer = useRef<number | undefined>(undefined)
  const latest = useRef<string>('')
  const item = doc.kind === 'library' ? rooms.library.find((i) => i.id === doc.id) : undefined
  const name = doc.kind === 'own' ? OWN_NAMES[doc.doc] : item?.name ?? t('libDocument')
  const editable = doc.kind === 'own' || Boolean(item && /\.(md|markdown|txt)$/i.test(item.name))

  // the text: the agent's documents from the rooms, a Library file from disk
  useEffect(() => {
    let alive = true
    const load = doc.kind === 'own'
      ? roomsCall<Record<DocName, DocText>>('docs').then((docs) => docs[doc.doc].text)
      : fetch(fileUrl(doc.id, false)).then(async (res) => {
          const json = (await res.json().catch(() => ({}))) as { text?: string; error?: { message?: string } }
          if (!res.ok) throw new Error(json.error?.message ?? `${res.status}`)
          return json.text ?? ''
        })
    load.then((value) => { if (alive) { latest.current = value; setText(value) } }).catch((err: unknown) => { if (alive) setError(failureText(t, err)) })
    return () => { alive = false }
  }, [doc])

  // the editable shows the rendering; it is set once per load and per source toggle
  useEffect(() => {
    if (text === null || source || !body.current) return
    body.current.innerHTML = mdToHtml(latest.current)
  }, [text === null, source])

  const persist = useCallback(async (value: string) => {
    setSaved('saving')
    try {
      if (doc.kind === 'own') await roomsCall('docs/write', { doc: doc.doc, text: value })
      else await roomsCall('library/write', { id: doc.id, text: value })
      setSaved('saved')
    } catch (err: unknown) {
      setError(failureText(t, err))
      setSaved('dirty')
    }
  }, [doc, t])

  const changed = (value: string) => {
    latest.current = value
    setSaved('dirty')
    if (timer.current) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => { void persist(latest.current) }, SAVE_AFTER_MS)
  }
  const onInput = () => { if (body.current && editable) changed(htmlToMd(body.current.innerHTML)) }
  useEffect(() => () => {
    if (timer.current) {
      window.clearTimeout(timer.current)
      void persist(latest.current)
    }
  }, [persist])

  const close = () => win.openDoc(null)
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape' && !event.defaultPrevented) close() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const exec = (command: string, value?: string) => {
    body.current?.focus()
    document.execCommand(command, false, value)
    onInput()
  }
  const toolbar: { id: string; label: string; title: string; run(): void }[] = [
    { id: 'b', label: 'B', title: t('edBold'), run: () => exec('bold') },
    { id: 'i', label: 'I', title: t('edItalic'), run: () => exec('italic') },
    { id: 'h1', label: 'H1', title: t('edHeading', { n: 1 }), run: () => exec('formatBlock', 'h1') },
    { id: 'h2', label: 'H2', title: t('edHeading', { n: 2 }), run: () => exec('formatBlock', 'h2') },
    { id: 'h3', label: 'H3', title: t('edHeading', { n: 3 }), run: () => exec('formatBlock', 'h3') },
    { id: 'ul', label: '•', title: t('edBullets'), run: () => exec('insertUnorderedList') },
    { id: 'ol', label: '1.', title: t('edNumbers'), run: () => exec('insertOrderedList') },
  ]

  const download = () => {
    const blob = new Blob([latest.current], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = name
    document.body.appendChild(a)
    a.click()
    a.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 2000)
  }
  const menu: (MenuChoice | 'sep')[] = [
    { id: 'source', label: source ? t('edRendered') : t('edSource'), icon: h(IconCode, { size: 16 }), onSelect: () => setSource((s) => !s) },
    { id: 'copy', label: t('edCopy'), icon: h(IconCopy, { size: 16 }), onSelect: () => { void navigator.clipboard?.writeText(latest.current) } },
    { id: 'download', label: t('edDownload'), icon: h(IconDownload, { size: 16 }), onSelect: download },
    { id: 'pdf', label: t('edPdf'), icon: h(IconDownload, { size: 16 }), onSelect: () => { document.documentElement.setAttribute('data-nm-print', 'doc'); window.setTimeout(() => { window.print(); document.documentElement.removeAttribute('data-nm-print') }, 50) } },
    'sep',
    doc.kind === 'own'
      ? { id: 'reset', label: t('edReset'), icon: h(IconRefresh, { size: 16 }), danger: true, onSelect: () => { if (doc.doc !== 'memory' && window.confirm(t('edResetConfirm', { name }))) { latest.current = ''; void persist('').then(() => roomsCall<Record<DocName, DocText>>('docs')).then((docs) => { if (docs) { latest.current = docs[doc.doc].text; setText(docs[doc.doc].text); if (body.current) body.current.innerHTML = mdToHtml(latest.current) } }) } } }
      : { id: 'delete', label: t('edDelete'), icon: h(IconTrash, { size: 16 }), danger: true, onSelect: () => { void roomsCall('library/delete', { id: doc.id }).then(close) } },
  ]

  return h('section', { className: 'nm-doc', role: 'dialog', 'aria-label': name },
    h('div', { className: 'nm-doc-bar', 'data-window-drag': true },
      h('button', { type: 'button', className: 'nm-icon-btn', title: t('menuCollapse'), 'aria-label': t('menuCollapse'), onClick: toggleSidebar }, h(IconLayout, { size: 18 })),
      h('div', { className: 'nm-doc-name', title: item?.path ?? name }, name),
      editable && !source
        ? h('div', { className: 'nm-doc-tools', role: 'toolbar' }, toolbar.map((b) => h('button', { key: b.id, type: 'button', className: `nm-doc-tool nm-doc-tool-${b.id}`, title: b.title, 'aria-label': b.title, onMouseDown: (e: MouseEvent) => e.preventDefault(), onClick: b.run }, b.label)))
        : h('div', { className: 'nm-doc-tools' }),
      h('span', { className: 'nm-doc-state' }, saved === 'saving' ? t('edSaving') : saved === 'saved' ? t('edSaved') : saved === 'dirty' ? t('edUnsaved') : ''),
      h(MoreButton, { label: t('more'), items: menu }),
      h('button', { type: 'button', className: 'nm-icon-btn', title: t('close'), 'aria-label': t('close'), onClick: close }, h(IconClose, { size: 18 }))),
    error ? h('div', { className: 'nm-doc-error', role: 'alert' }, error) : null,
    text === null
      ? h('div', { className: 'nm-doc-loading' }, t('loading'))
      : source
        ? h('textarea', { className: 'nm-doc-source', defaultValue: latest.current, spellCheck: false, readOnly: !editable, onChange: (e: FormEvent<HTMLTextAreaElement>) => changed(e.currentTarget.value) })
        : h('div', { ref: body, className: 'nm-doc-body nm-md', contentEditable: editable, suppressContentEditableWarning: true, spellCheck: false, onInput, onBlur: () => { if (timer.current) { window.clearTimeout(timer.current); timer.current = undefined; void persist(latest.current) } } }))
}
