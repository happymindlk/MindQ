import { useMemo } from 'react';
import type { ReactNode } from 'react';
import { DndContext, DragOverlay, closestCenter, useDraggable, useDroppable } from '@dnd-kit/core';
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { Check, GripVertical, Plus } from 'lucide-react';
import { usePackageComposer } from '../hooks/use-package-composer';
import { LIBRARY_DRAG_PREFIX, SEQUENCE_DROP_ID, libraryDragId } from '../lib/composer-logic';
import { CATEGORY_LABELS } from '../types/module';
import type { AssessmentCategory, CatalogModule } from '../types/module';
import { ModuleCard } from './module-card';

interface ComposerDndProviderProps {
  cartIds: string[];
  locked: boolean;
  catalogById: Map<string, CatalogModule>;
  onReorder: (ids: string[]) => void;
  onAdd: (moduleId: string, nextIds: string[]) => void;
  children: ReactNode;
}

export function ComposerDndProvider({ cartIds, locked, catalogById, onReorder, onAdd, children }: ComposerDndProviderProps) {
  const { sensors, activeId, onDragStart, onDragEnd, onDragCancel } = usePackageComposer({
    cartIds,
    locked,
    onReorder,
    onAdd,
  });
  const activeModuleId = activeId?.startsWith(LIBRARY_DRAG_PREFIX) ? activeId.slice(LIBRARY_DRAG_PREFIX.length) : activeId;
  const activeModule = activeModuleId ? catalogById.get(activeModuleId) : undefined;

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDragCancel={onDragCancel}
      accessibility={{
        screenReaderInstructions: {
          draggable:
            'Press space or enter to pick up a module. Use arrow keys to move it in the sequence, space or enter to drop, escape to cancel.',
        },
      }}
    >
      {children}
      <DragOverlay dropAnimation={null}>
        {activeModule ? (
          <div className="w-72 rotate-1 opacity-95">
            <ModuleCard module={activeModule} compact active />
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  );
}

function DraggableLibraryCard({
  module,
  added,
  locked,
  onAdd,
}: {
  module: CatalogModule;
  added: boolean;
  locked: boolean;
  onAdd: (id: string) => void;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: libraryDragId(module.id),
    disabled: locked || added,
  });
  return (
    <li ref={setNodeRef} className={isDragging ? 'opacity-40' : undefined}>
      <ModuleCard
        module={module}
        compact
        trailing={
          <span className="flex shrink-0 items-center gap-1">
            {!locked && !added && (
              <button
                type="button"
                {...attributes}
                {...listeners}
                aria-label={`Drag ${module.title} into the suite`}
                className="cursor-grab rounded p-1 text-slate-400 hover:text-indigo-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 active:cursor-grabbing dark:text-slate-500 dark:hover:text-indigo-300"
              >
                <GripVertical className="h-4 w-4" />
              </button>
            )}
            <button
              type="button"
              onClick={() => onAdd(module.id)}
              disabled={locked || added}
              aria-label={added ? `${module.title} is in the suite` : `Add ${module.title} to the suite`}
              className={`inline-flex h-7 items-center gap-1 rounded-md border px-2 text-[11px] font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                added
                  ? 'border-emerald-300 text-emerald-700 dark:border-emerald-500/40 dark:text-emerald-300'
                  : 'border-slate-200 text-slate-700 hover:border-indigo-400 hover:bg-indigo-50 hover:text-indigo-700 disabled:opacity-40 dark:border-slate-700 dark:text-slate-300 dark:hover:border-indigo-500/60 dark:hover:bg-indigo-950/40 dark:hover:text-indigo-300'
              }`}
            >
              {added ? <Check className="h-3 w-3" aria-hidden /> : <Plus className="h-3 w-3" aria-hidden />}
              {added ? 'Added' : 'Add'}
            </button>
          </span>
        }
      />
    </li>
  );
}

type GroupKey = AssessmentCategory | 'technical' | 'other';

const GROUP_ORDER: GroupKey[] = ['behavioral', 'cognitive', 'personality', 'other', 'technical'];
const GROUP_LABELS: Record<GroupKey, string> = {
  ...CATEGORY_LABELS,
  other: 'Psychometric',
  technical: 'Technical',
};

interface ComposerLibraryPaneProps {
  modules: CatalogModule[];
  search: string;
  selectedIds: ReadonlySet<string>;
  locked: boolean;
  onAdd: (id: string) => void;
}

export function ComposerLibraryPane({ modules, search, selectedIds, locked, onAdd }: ComposerLibraryPaneProps) {
  const groups = useMemo(() => {
    const query = search.trim().toLowerCase();
    const map = new Map<GroupKey, CatalogModule[]>();
    for (const module of modules) {
      const haystack = `${module.title} ${module.description ?? ''} ${module.assessmentCategory ?? module.moduleKind}`.toLowerCase();
      if (query && !haystack.includes(query)) continue;
      const key: GroupKey = module.moduleKind === 'technical' ? 'technical' : module.assessmentCategory ?? 'other';
      map.set(key, [...(map.get(key) ?? []), module]);
    }
    return GROUP_ORDER.filter((key) => (map.get(key)?.length ?? 0) > 0).map((key) => ({ key, items: map.get(key) ?? [] }));
  }, [modules, search]);

  if (groups.length === 0) {
    return (
      <p className="px-4 py-8 text-center text-sm text-slate-500 dark:text-slate-400">
        {search.trim() ? 'No published modules match this search.' : 'No published modules yet. Publish a module in the Standard Library.'}
      </p>
    );
  }

  return (
    <div className="space-y-4 p-3">
      {groups.map(({ key, items }) => (
        <section key={key} aria-label={`${GROUP_LABELS[key]} modules`} className="space-y-2">
          <h3 className="flex items-center gap-2 px-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            {GROUP_LABELS[key]}
            <span className="font-mono tabular-nums text-slate-400 dark:text-slate-600">{items.length}</span>
          </h3>
          <ul className="space-y-2">
            {items.map((module) => (
              <DraggableLibraryCard
                key={module.id}
                module={module}
                added={selectedIds.has(module.id)}
                locked={locked}
                onAdd={onAdd}
              />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function SortableSequenceItem({
  id,
  index,
  locked,
  renderItem,
}: {
  id: string;
  index: number;
  locked: boolean;
  renderItem: (id: string, handle: ReactNode) => ReactNode;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id, disabled: locked });
  const handle = (
    <span className="flex items-center gap-1.5">
      <span className="font-mono text-[10px] tabular-nums text-slate-400 dark:text-slate-500">{String(index + 1).padStart(2, '0')}</span>
      {!locked && (
        <button
          type="button"
          {...attributes}
          {...listeners}
          aria-label={`Reorder module ${index + 1}`}
          className="cursor-grab rounded p-0.5 text-slate-400 hover:text-indigo-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 active:cursor-grabbing dark:text-slate-500 dark:hover:text-indigo-300"
        >
          <GripVertical className="h-3.5 w-3.5" />
        </button>
      )}
    </span>
  );
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={isDragging ? 'relative z-10 opacity-60' : undefined}
    >
      {renderItem(id, handle)}
    </li>
  );
}

interface ComposerSequenceProps {
  cartIds: string[];
  locked: boolean;
  renderItem: (id: string, handle: ReactNode) => ReactNode;
  emptyState: ReactNode;
}

export function ComposerSequence({ cartIds, locked, renderItem, emptyState }: ComposerSequenceProps) {
  const { setNodeRef, isOver } = useDroppable({ id: SEQUENCE_DROP_ID, disabled: locked });
  return (
    <div
      ref={setNodeRef}
      className={`rounded-xl transition-all ${
        isOver ? 'outline outline-2 outline-offset-4 outline-indigo-500/60 dark:outline-indigo-400/60' : ''
      }`}
    >
      {cartIds.length === 0 ? (
        emptyState
      ) : (
        <SortableContext items={cartIds} strategy={verticalListSortingStrategy}>
          <ol className="space-y-2" aria-label="Suite module sequence">
            {cartIds.map((id, index) => (
              <SortableSequenceItem key={id} id={id} index={index} locked={locked} renderItem={renderItem} />
            ))}
          </ol>
        </SortableContext>
      )}
    </div>
  );
}
