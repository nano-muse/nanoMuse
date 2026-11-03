/** Do two answers carry the same values? A poll hands back a fresh object even
 *  when nothing changed, so an editor's drafts may only be reseeded when the
 *  values themselves moved. */
export const sameDraft = (seeded: unknown, incoming: unknown): boolean =>
  JSON.stringify(seeded) === JSON.stringify(incoming);
