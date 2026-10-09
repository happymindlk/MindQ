import type { AssessmentCategory, CatalogModule, ModuleKind, TimerMode } from '../types/module';

const CATEGORIES: readonly string[] = ['behavioral', 'cognitive', 'personality'];

function str(value: unknown): string | null {
  return typeof value === 'string' && value ? value : null;
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/**
 * Normalize a loosely-typed module row (catalog API, or a module embedded in a
 * saved package) into a CatalogModule. Missing fields fall back to safe defaults
 * so legacy package snapshots still render.
 *
 * @param row - Snake_case row from the admin API.
 * @returns Normalized catalog module.
 */
export function catalogFromRow(row: Record<string, unknown>): CatalogModule {
  const kind: ModuleKind = row.module_kind === 'technical' ? 'technical' : 'psychometric';
  const rawCategory = str(row.assessment_category);
  const category = rawCategory && CATEGORIES.includes(rawCategory) ? (rawCategory as AssessmentCategory) : null;
  const durationSeconds = num(row.duration_seconds) || (num(row.time_limit_minutes) ?? 0) * 60 || null;
  const questions = Array.isArray(row.questions) ? row.questions : [];
  const timerMode: TimerMode = row.timer_mode === 'strict' ? 'strict' : 'flexible';
  return {
    id: String(row.id ?? row.module_id ?? ''),
    title: str(row.title) ?? 'Untitled module',
    description: str(row.description),
    moduleKind: kind,
    assessmentCategory: kind === 'psychometric' ? category : null,
    durationSeconds,
    timerMode,
    shuffleQuestions: row.shuffle_questions === true,
    version: num(row.version) ?? 1,
    questionCount: num(row.question_count) ?? questions.length,
    facetCount: num(row.facet_count) ?? 0,
  };
}
