// The settings dialog's shell state, kept apart from the React so a test can drive it:
// open or closed, the page shown, and the page a link came from (the way back).

/**
 * Shell state: whether the dialog is open, which page shows, and the page a link on
 * another page came from (`from`), so the head can offer the way back. A pick in the
 * left-hand list is a fresh start and clears it.
 */
export interface ShellState {
  open: boolean
  activeId: string | undefined
  from: string | undefined
}
export function createShellStore() {
  let state: ShellState = { open: false, activeId: undefined, from: undefined }
  const listeners = new Set<() => void>()
  const set = (next: ShellState) => { state = next; for (const l of listeners) l() }
  return {
    getSnapshot: () => state,
    subscribe: (l: () => void) => { listeners.add(l); return () => { listeners.delete(l) } },
    open: () => set({ ...state, open: true }),
    close: () => set({ open: false, activeId: undefined, from: undefined }),
    select: (id: string) => set({ ...state, activeId: id, from: undefined }),
    openSection: (id: string) => set({ open: true, activeId: id, from: state.open && state.activeId !== undefined && state.activeId !== id ? state.activeId : undefined }),
    back: () => { if (state.from !== undefined) set({ open: true, activeId: state.from, from: undefined }) },
    toggle: () => (state.open ? set({ open: false, activeId: undefined, from: undefined }) : set({ ...state, open: true })),
  }
}
export type ShellStore = ReturnType<typeof createShellStore>
