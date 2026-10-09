import type { TemplateQuestion } from './question';

export type AssessmentCategory = 'behavioral' | 'cognitive' | 'personality';
export type ModuleKind = 'psychometric' | 'technical';
export type ModuleStatus = 'draft' | 'published';
export type TimerMode = 'strict' | 'flexible';

export const ASSESSMENT_CATEGORIES: readonly AssessmentCategory[] = [
  'behavioral',
  'cognitive',
  'personality',
] as const;

export const CATEGORY_LABELS: Record<AssessmentCategory, string> = {
  behavioral: 'Behavioral',
  cognitive: 'Cognitive',
  personality: 'Personality',
};

/** Library module in camelCase, normalized from the snake_case API rows. */
export interface AssessmentModule {
  id: string;
  slug: string;
  title: string;
  description: string | null;
  moduleKind: ModuleKind;
  assessmentCategory: AssessmentCategory | null;
  /** Seconds; null means untimed. */
  durationSeconds: number | null;
  timerMode: TimerMode;
  shuffleQuestions: boolean;
  status: ModuleStatus;
  version: number;
  lineageId: string;
  parentModuleId: string | null;
  /** Published, or linked to a live candidate package. Destructive edits are blocked. */
  isLocked: boolean;
  linkedPackageCount: number;
  questionCount: number;
  facetCount: number;
  isActive: boolean;
  position: number;
}

export interface AssessmentModuleDetail extends AssessmentModule {
  questions: TemplateQuestion[];
}

/** Runner configuration editable while a module is a draft. */
export interface ModuleSettings {
  durationSeconds: number | null;
  timerMode: TimerMode;
  shuffleQuestions: boolean;
}

export interface ModuleCreateInput {
  title: string;
  moduleKind: ModuleKind;
  assessmentCategory: AssessmentCategory | null;
  description: string;
  settings: ModuleSettings;
}

/** Catalog row from `GET /packages/modules` used by the package composer. */
export interface CatalogModule {
  id: string;
  title: string;
  description: string | null;
  moduleKind: ModuleKind;
  assessmentCategory: AssessmentCategory | null;
  durationSeconds: number | null;
  timerMode: TimerMode;
  shuffleQuestions: boolean;
  version: number;
  questionCount: number;
  facetCount: number;
}

/**
 * Format a duration for pill tags.
 *
 * @param seconds - Duration in seconds, or null/0 for untimed.
 * @returns e.g. "15 min", "2 min 30 s", or "Untimed".
 */
export function formatDuration(seconds: number | null): string {
  if (!seconds) return 'Untimed';
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes === 0) return `${rest} s`;
  return rest ? `${minutes} min ${rest} s` : `${minutes} min`;
}

export function statusLabel(module: Pick<AssessmentModule, 'status' | 'version' | 'isLocked'>): string {
  if (module.status === 'published') return `v${module.version} - Published (Locked)`;
  if (module.isLocked) return `v${module.version} - Live (Locked)`;
  return `v${module.version} - Draft`;
}
