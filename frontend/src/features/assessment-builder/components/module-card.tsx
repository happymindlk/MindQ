import { memo } from 'react';
import type { ReactNode } from 'react';
import { Archive, Layers, ListChecks, Lock, ShieldAlert, Shuffle, Timer, TimerOff } from 'lucide-react';
import { CATEGORY_LABELS, formatDuration, statusLabel } from '../types/module';
import type { AssessmentCategory, ModuleKind, ModuleStatus, TimerMode } from '../types/module';
import { Pill } from './primitives';
import type { Tone } from './primitives';
import { CATEGORY_TONES } from './tones';

/** Fields a card needs; satisfied by both library modules and catalog rows. */
export interface ModuleCardData {
  id: string;
  title: string;
  description: string | null;
  moduleKind: ModuleKind;
  assessmentCategory: AssessmentCategory | null;
  durationSeconds: number | null;
  timerMode: TimerMode;
  shuffleQuestions: boolean;
  questionCount: number;
  facetCount: number;
  version: number;
  status?: ModuleStatus;
  isLocked?: boolean;
}

interface ModuleCardProps {
  module: ModuleCardData;
  active?: boolean;
  onOpen?: (id: string) => void;
  onArchive?: (id: string) => void;
  /** Rendered in the top-right; used by the composer for drag handles / add buttons. */
  trailing?: ReactNode;
  compact?: boolean;
}

function enforcement(module: ModuleCardData): { label: string; tone: Tone; strict: boolean } {
  if (module.durationSeconds && module.timerMode === 'strict') {
    return { label: 'Strict Timer', tone: 'amber', strict: true };
  }
  return { label: module.durationSeconds ? 'Flexible' : 'Flexible/Untimed', tone: 'neutral', strict: false };
}

function ModuleCardImpl({ module, active = false, onOpen, onArchive, trailing, compact = false }: ModuleCardProps) {
  const category = module.assessmentCategory;
  const enforce = enforcement(module);
  const status = module.status ?? 'published';
  const locked = status === 'published' || Boolean(module.isLocked);
  const interactive = Boolean(onOpen);

  const body = (
    <>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">{module.title}</h3>
          {!compact && module.description && (
            <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-500 dark:text-slate-400">{module.description}</p>
          )}
        </div>
        {trailing}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {category ? (
          <Pill tone={CATEGORY_TONES[category]}>{CATEGORY_LABELS[category]}</Pill>
        ) : (
          <Pill tone="neutral">Technical</Pill>
        )}
        <Pill tone="indigo" icon={<Layers className="h-3 w-3" aria-hidden />} title="Sub-dimensions">
          {module.facetCount} {module.facetCount === 1 ? 'facet' : 'facets'}
        </Pill>
        <Pill
          icon={module.durationSeconds ? <Timer className="h-3 w-3" aria-hidden /> : <TimerOff className="h-3 w-3" aria-hidden />}
        >
          {formatDuration(module.durationSeconds)}
        </Pill>
        <Pill icon={<ListChecks className="h-3 w-3" aria-hidden />}>
          {module.questionCount} {module.questionCount === 1 ? 'Item' : 'Items'}
        </Pill>
        <Pill tone={enforce.tone} icon={enforce.strict ? <ShieldAlert className="h-3 w-3" aria-hidden /> : undefined}>
          {enforce.label}
        </Pill>
        {module.shuffleQuestions && (
          <Pill tone="violet" icon={<Shuffle className="h-3 w-3" aria-hidden />}>
            Randomized
          </Pill>
        )}
      </div>

      {!compact && (
        <div className="mt-3 flex items-center justify-between gap-2 border-t border-slate-200 pt-3 dark:border-slate-800/80">
          <Pill
            tone={locked ? 'cyan' : 'amber'}
            icon={locked ? <Lock className="h-3 w-3" aria-hidden /> : undefined}
          >
            {statusLabel({ status, version: module.version, isLocked: locked })}
          </Pill>
        </div>
      )}
    </>
  );

  const shell = `group relative rounded-xl border bg-white p-4 transition-all dark:bg-slate-900 ${
    active
      ? 'border-indigo-500 ring-1 ring-indigo-500/30 dark:border-indigo-400'
      : 'border-slate-200 hover:border-slate-300 dark:border-slate-800 dark:hover:border-slate-600'
  }`;

  return (
    <article className={shell} aria-current={active || undefined}>
      {interactive ? (
        <button
          type="button"
          onClick={() => onOpen?.(module.id)}
          className="block w-full rounded-lg text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-4 focus-visible:ring-offset-white dark:focus-visible:ring-indigo-400 dark:focus-visible:ring-offset-slate-900"
          aria-label={`Open ${module.title}`}
        >
          {body}
        </button>
      ) : (
        body
      )}
      {onArchive && !compact && (
        <button
          type="button"
          onClick={() => onArchive(module.id)}
          className="absolute bottom-3 right-3 inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-slate-500 transition-colors hover:bg-rose-500/10 hover:text-rose-600 dark:text-slate-400 dark:hover:text-rose-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400"
          aria-label={`Archive ${module.title}`}
        >
          <Archive className="h-3.5 w-3.5" aria-hidden />
          Archive
        </button>
      )}
    </article>
  );
}

export const ModuleCard = memo(ModuleCardImpl);
