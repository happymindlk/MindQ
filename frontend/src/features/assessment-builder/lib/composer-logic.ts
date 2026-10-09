export const LIBRARY_DRAG_PREFIX = 'library:';
export const SEQUENCE_DROP_ID = 'composer-sequence';

export type ComposerDragResult =
  | { kind: 'add'; moduleId: string; index: number }
  | { kind: 'reorder'; ids: string[] }
  | null;

export function libraryDragId(moduleId: string): string {
  return `${LIBRARY_DRAG_PREFIX}${moduleId}`;
}

/**
 * Move one element of an array to a new index without mutating the input.
 *
 * @param items - Source array.
 * @param from - Current index.
 * @param to - Target index.
 * @returns New array with the element moved.
 */
export function moveItem<T>(items: readonly T[], from: number, to: number): T[] {
  const next = [...items];
  const [moved] = next.splice(from, 1);
  if (moved === undefined) return next;
  next.splice(Math.max(0, Math.min(to, next.length)), 0, moved);
  return next;
}

/**
 * Translate a dnd-kit drag-end into a composer mutation.
 *
 * Library cards dropped on a sequence item insert before it; dropped on the
 * empty sequence area they append. Sequence items dropped on each other reorder.
 *
 * @param cartIds - Current module sequence.
 * @param activeId - Dragged item id (library ids carry LIBRARY_DRAG_PREFIX).
 * @param overId - Drop target id, or null when dropped outside.
 * @returns Mutation to apply, or null for a no-op.
 */
export function resolveDragEnd(
  cartIds: readonly string[],
  activeId: string,
  overId: string | null,
): ComposerDragResult {
  if (overId === null) return null;

  if (activeId.startsWith(LIBRARY_DRAG_PREFIX)) {
    const moduleId = activeId.slice(LIBRARY_DRAG_PREFIX.length);
    if (!moduleId || cartIds.includes(moduleId)) return null;
    const overIndex = cartIds.indexOf(overId);
    if (overId !== SEQUENCE_DROP_ID && overIndex === -1) return null;
    return { kind: 'add', moduleId, index: overIndex === -1 ? cartIds.length : overIndex };
  }

  if (activeId === overId) return null;
  const from = cartIds.indexOf(activeId);
  const to = overId === SEQUENCE_DROP_ID ? cartIds.length - 1 : cartIds.indexOf(overId);
  if (from === -1 || to === -1 || from === to) return null;
  return { kind: 'reorder', ids: moveItem(cartIds, from, to) };
}

/**
 * Insert an id at an index, ignoring duplicates.
 *
 * @param ids - Current sequence.
 * @param id - Module to add.
 * @param index - Insert position (clamped).
 * @returns New sequence.
 */
export function insertAt(ids: readonly string[], id: string, index: number): string[] {
  if (ids.includes(id)) return [...ids];
  const next = [...ids];
  next.splice(Math.max(0, Math.min(index, next.length)), 0, id);
  return next;
}
