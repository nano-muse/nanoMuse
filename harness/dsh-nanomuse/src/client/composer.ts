/**
 * The harness's composer, from outside: its editable, words put into it (Muse
 * prefills "I want to create an image of …" when a Library button is pressed),
 * and its card's position (the quote chip sits above it).
 */

export function composerEditable(): HTMLElement | null {
  return document.querySelector<HTMLElement>('[data-composer-card] [contenteditable="true"]') ?? document.querySelector<HTMLElement>('[data-slot="conversation.composer"] [contenteditable="true"]')
}

export function composerCard(): HTMLElement | null {
  return document.querySelector<HTMLElement>('[data-composer-card]')
}

/**
 * Put words in the composer, replacing a draft, with the caret at the end. `insertText`
 * goes through the editor's own input handling, so its state follows. Retries for a
 * moment: the chat the words are for may still be mounting.
 */
export function prefillComposer(text: string, tries = 30): void {
  const editable = composerEditable()
  if (!editable) {
    if (tries > 0) window.setTimeout(() => prefillComposer(text, tries - 1), 150)
    return
  }
  editable.focus()
  const selection = window.getSelection()
  if (selection) {
    const range = document.createRange()
    range.selectNodeContents(editable)
    selection.removeAllRanges()
    selection.addRange(range)
  }
  const ok = document.execCommand('insertText', false, text)
  if (!ok) {
    editable.textContent = text
    editable.dispatchEvent(new InputEvent('input', { bubbles: true, data: text, inputType: 'insertText' }))
  }
}

export function focusComposer(tries = 8): void {
  const editable = composerEditable()
  if (editable) {
    editable.focus()
    return
  }
  if (tries > 0) window.setTimeout(() => focusComposer(tries - 1), 150)
}

/** A first-run task waits for its chat and never replaces an existing draft. */
export function prefillEmptyComposer(text: string, isTarget: () => boolean, tries = 30): void {
  const editable = isTarget() ? composerEditable() : null
  if (!editable) {
    if (tries > 0) window.setTimeout(() => prefillEmptyComposer(text, isTarget, tries - 1), 150)
    return
  }
  if (editable.textContent?.trim()) return
  prefillComposer(text, 0)
}
