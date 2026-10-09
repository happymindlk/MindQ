import { useCallback, useState } from 'react';
import { KeyboardSensor, PointerSensor, useSensor, useSensors } from '@dnd-kit/core';
import type { DragEndEvent, DragStartEvent } from '@dnd-kit/core';
import { sortableKeyboardCoordinates } from '@dnd-kit/sortable';
import { insertAt, resolveDragEnd } from '../lib/composer-logic';

export interface PackageComposerOptions {
  cartIds: string[];
  locked: boolean;
  onReorder: (ids: string[]) => void;
  onAdd: (moduleId: string, nextIds: string[]) => void;
}

/**
 * dnd-kit wiring for the package composer. The host page owns `cartIds`
 * (it autosaves them), so this hook only translates drag events.
 *
 * @param options - Current sequence plus mutation callbacks.
 * @returns Sensors, handlers, and the id currently being dragged.
 */
export function usePackageComposer({ cartIds, locked, onReorder, onAdd }: PackageComposerOptions) {
  const [activeId, setActiveId] = useState<string | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const onDragStart = useCallback((event: DragStartEvent) => {
    setActiveId(String(event.active.id));
  }, []);

  const onDragCancel = useCallback(() => setActiveId(null), []);

  const onDragEnd = useCallback(
    (event: DragEndEvent) => {
      setActiveId(null);
      if (locked) return;
      const result = resolveDragEnd(cartIds, String(event.active.id), event.over ? String(event.over.id) : null);
      if (!result) return;
      if (result.kind === 'reorder') onReorder(result.ids);
      else onAdd(result.moduleId, insertAt(cartIds, result.moduleId, result.index));
    },
    [cartIds, locked, onAdd, onReorder],
  );

  return { sensors, activeId, onDragStart, onDragEnd, onDragCancel };
}
