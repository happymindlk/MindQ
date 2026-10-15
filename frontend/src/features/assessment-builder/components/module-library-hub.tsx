import { useMemo } from 'react';
import { Brain, Code2, Plus, Sparkles, Users } from 'lucide-react';
import type { ReactNode } from 'react';
import { ASSESSMENT_CATEGORIES, CATEGORY_LABELS } from '../types/module';
import type { AssessmentCategory, AssessmentModule, ModuleKind } from '../types/module';
import { ModuleCard } from './module-card';

export type HubFilter = 'all' | 'psychometric' | 'technical';

type SectionKey = AssessmentCategory | 'uncategorized' | 'technical';

interface SectionDef {
  key: SectionKey;
  label: string;
  blurb: string;
  icon: ReactNode;
  kind: ModuleKind;
  category: AssessmentCategory | null;
}

const SECTION_META: Record<SectionKey, Omit<SectionDef, 'key'>> = {
  behavioral: {
    label: CATEGORY_LABELS.behavioral,
    blurb: 'Situational judgment, integrity, and workplace conduct.',
    icon: <Users className="h-4 w-4 text-violet-600 dark:text-violet-300" aria-hidden />,
    kind: 'psychometric',
    category: 'behavioral',
  },
  cognitive: {
    label: CATEGORY_LABELS.cognitive,
    blurb: 'Verbal, matrix, numerical reasoning and CRT. Usually strict-timed.',
    icon: <Brain className="h-4 w-4 text-cyan-600 dark:text-cyan-300" aria-hidden />,
    kind: 'psychometric',
    category: 'cognitive',
  },
  personality: {
    label: CATEGORY_LABELS.personality,
    blurb: 'IPIP / HEXACO style Likert inventories. Usually untimed and shuffled.',
    icon: <Sparkles className="h-4 w-4 text-emerald-600 dark:text-emerald-300" aria-hidden />,
    kind: 'psychometric',
    category: 'personality',
  },
  uncategorized: {
    label: 'Uncategorized Psychometric',
    blurb: 'Assign a category in the module editor.',
    icon: <Brain className="h-4 w-4 text-slate-500 dark:text-slate-400" aria-hidden />,
    kind: 'psychometric',
    category: null,
  },
  technical: {
    label: 'Technical',
    blurb: 'Role-specific skills, MCQ, and open-ended tasks.',
    icon: <Code2 className="h-4 w-4 text-slate-600 dark:text-slate-300" aria-hidden />,
    kind: 'technical',
    category: null,
  },
};

function sectionOf(module: AssessmentModule): SectionKey {
  if (module.moduleKind === 'technical') return 'technical';
  return module.assessmentCategory ?? 'uncategorized';
}

function matches(module: AssessmentModule, query: string): boolean {
  if (!query) return true;
  const haystack = `${module.title} ${module.description ?? ''} ${module.assessmentCategory ?? module.moduleKind}`;
  return haystack.toLowerCase().includes(query);
}

interface ModuleLibraryHubProps {
  modules: AssessmentModule[];
  filter: HubFilter;
  search: string;
  activeId: string | null;
  loading: boolean;
  onOpen: (id: string) => void;
  onArchive: (id: string) => void;
  onCreate: (kind: ModuleKind, category: AssessmentCategory | null) => void;
}

export function ModuleLibraryHub({
  modules,
  filter,
  search,
  activeId,
  loading,
  onOpen,
  onArchive,
  onCreate,
}: ModuleLibraryHubProps) {
  const grouped = useMemo(() => {
    const query = search.trim().toLowerCase();
    const map = new Map<SectionKey, AssessmentModule[]>();
    for (const module of modules) {
      if (!matches(module, query)) continue;
      const key = sectionOf(module);
      const bucket = map.get(key) ?? [];
      bucket.push(module);
      map.set(key, bucket);
    }
    for (const bucket of map.values()) {
      bucket.sort((a, b) =>
        a.lineageId === b.lineageId ? b.version - a.version : a.position - b.position || a.title.localeCompare(b.title),
      );
    }
    return map;
  }, [modules, search]);

  const sections: SectionKey[] = useMemo(() => {
    const psych: SectionKey[] = [...ASSESSMENT_CATEGORIES];
    if ((grouped.get('uncategorized')?.length ?? 0) > 0) psych.push('uncategorized');
    if (filter === 'psychometric') return psych;
    if (filter === 'technical') return ['technical'];
    return [...psych, 'technical'];
  }, [filter, grouped]);

  if (loading) {
    return (
      <div className="grid gap-6" aria-busy="true" aria-label="Loading assessment library">
        {[0, 1, 2].map((i) => (
          <div key={i} className="space-y-3">
            <div className="h-5 w-40 animate-pulse rounded bg-slate-200 dark:bg-slate-800" />
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {[0, 1, 2].map((j) => (
                <div key={j} className="h-40 animate-pulse rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900" />
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {sections.map((key) => {
        const meta = SECTION_META[key];
        const items = grouped.get(key) ?? [];
        const headingId = `hub-section-${key}`;
        return (
          <section key={key} aria-labelledby={headingId} className="space-y-3">
            <header className="flex flex-wrap items-end justify-between gap-2">
              <div className="flex items-start gap-2">
                <span className="mt-0.5 rounded-lg border border-slate-200 bg-white p-1.5 dark:border-slate-800 dark:bg-slate-900">{meta.icon}</span>
                <div>
                  <h2 id={headingId} className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
                    {meta.label}
                    <span className="font-mono text-xs tabular-nums text-slate-400 dark:text-slate-500">{items.length}</span>
                  </h2>
                  <p className="text-xs text-slate-500 dark:text-slate-400">{meta.blurb}</p>
                </div>
              </div>
              {key !== 'uncategorized' && (
                <button
                  type="button"
                  onClick={() => onCreate(meta.kind, meta.category)}
                  className="inline-flex items-center gap-1 rounded-md border border-slate-200 px-2 py-1 text-xs font-medium text-slate-700 transition-colors hover:border-indigo-400 hover:text-indigo-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 dark:border-slate-800 dark:text-slate-300 dark:hover:border-indigo-500/60 dark:hover:text-indigo-300"
                >
                  <Plus className="h-3.5 w-3.5" aria-hidden />
                  New {meta.label} module
                </button>
              )}
            </header>

            {items.length === 0 ? (
              <div className="rounded-xl border border-dashed border-slate-300 bg-white px-4 py-6 text-center dark:border-slate-800 dark:bg-slate-950/60">
                <p className="text-sm text-slate-600 dark:text-slate-300">
                  {search.trim() ? 'No modules match this search.' : `No ${meta.label.toLowerCase()} modules yet.`}
                </p>
                {!search.trim() && key !== 'uncategorized' && (
                  <button
                    type="button"
                    onClick={() => onCreate(meta.kind, meta.category)}
                    className="mt-2 text-xs font-semibold text-indigo-600 hover:text-indigo-700 dark:text-indigo-300 dark:hover:text-indigo-200 focus:outline-none focus-visible:underline"
                  >
                    Create the first one
                  </button>
                )}
              </div>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {items.map((module) => (
                  <ModuleCard
                    key={module.id}
                    module={module}
                    active={module.id === activeId}
                    onOpen={onOpen}
                    onArchive={onArchive}
                  />
                ))}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
