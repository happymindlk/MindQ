import { supabase } from '../../../lib/supabaseClient';
import type {
  AssessmentCategory,
  AssessmentModule,
  AssessmentModuleDetail,
  CatalogModule,
  ModuleCreateInput,
  ModuleKind,
  ModuleSettings,
  ModuleStatus,
  TimerMode,
} from '../types/module';
import type { QuestionPayload, TemplateQuestion } from '../types/question';
import { ApiError, toApiError } from './api-error';

const API_BASE: string = import.meta.env.VITE_API_URL || '';

interface TemplateSummaryDto {
  id: string;
  slug: string;
  title: string;
  description: string | null;
  module_kind: ModuleKind;
  assessment_category: AssessmentCategory | null;
  duration_seconds: number | null;
  time_limit_minutes: number | null;
  timer_mode: TimerMode;
  shuffle_questions: boolean;
  status: ModuleStatus;
  version: number;
  lineage_id: string | null;
  parent_module_id: string | null;
  is_locked: boolean;
  linked_package_count: number;
  question_count: number;
  facet_count: number;
  is_active: boolean;
  position: number;
}

interface TemplateDetailDto extends TemplateSummaryDto {
  questions: TemplateQuestion[];
}

interface CatalogModuleDto {
  id: string;
  title: string;
  description: string | null;
  module_kind: ModuleKind;
  assessment_category: AssessmentCategory | null;
  duration_seconds: number | null;
  time_limit_minutes: number | null;
  timer_mode: TimerMode;
  shuffle_questions: boolean;
  version: number;
  question_count: number;
  facet_count: number;
}

/** Candidate-runner payload as produced by the backend sanitizer. */
export interface RunnerQuestion {
  id: string;
  text: string;
  type: string;
  options: string[];
  allow_multiple: boolean;
  media_url: string | null;
  likert_label_1: string | null;
  likert_label_5: string | null;
  scale_labels?: string[] | null;
}

export interface RunnerTest {
  id: string;
  title: string;
  description: string | null;
  time_limit_minutes: number | null;
  duration_seconds: number | null;
  timer_mode: TimerMode;
  shuffle_questions: boolean;
  started_at: string | null;
  questions: RunnerQuestion[];
  answers: Record<string, unknown>;
}

function durationOf(dto: { duration_seconds: number | null; time_limit_minutes: number | null }): number | null {
  if (dto.duration_seconds) return dto.duration_seconds;
  return dto.time_limit_minutes ? dto.time_limit_minutes * 60 : null;
}

export function toAssessmentModule(dto: TemplateSummaryDto): AssessmentModule {
  return {
    id: dto.id,
    slug: dto.slug,
    title: dto.title,
    description: dto.description,
    moduleKind: dto.module_kind,
    assessmentCategory: dto.assessment_category,
    durationSeconds: durationOf(dto),
    timerMode: dto.timer_mode,
    shuffleQuestions: dto.shuffle_questions,
    status: dto.status,
    version: dto.version,
    lineageId: dto.lineage_id ?? dto.id,
    parentModuleId: dto.parent_module_id,
    isLocked: dto.is_locked,
    linkedPackageCount: dto.linked_package_count,
    questionCount: dto.question_count,
    facetCount: dto.facet_count,
    isActive: dto.is_active,
    position: dto.position,
  };
}

function toDetail(dto: TemplateDetailDto): AssessmentModuleDetail {
  return { ...toAssessmentModule(dto), questions: dto.questions };
}

function toCatalogModule(dto: CatalogModuleDto): CatalogModule {
  return {
    id: dto.id,
    title: dto.title,
    description: dto.description,
    moduleKind: dto.module_kind,
    assessmentCategory: dto.assessment_category,
    durationSeconds: durationOf(dto),
    timerMode: dto.timer_mode,
    shuffleQuestions: dto.shuffle_questions,
    version: dto.version,
    questionCount: dto.question_count,
    facetCount: dto.facet_count,
  };
}

async function authHeaders(json: boolean): Promise<Record<string, string>> {
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const headers: Record<string, string> = {
    Authorization: `Bearer ${session?.access_token ?? ''}`,
  };
  if (json) headers['Content-Type'] = 'application/json';
  return headers;
}

async function request<T>(
  path: string,
  { method = 'GET', body, fallback }: { method?: string; body?: unknown; fallback: string },
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1${path}`, {
      method,
      headers: await authHeaders(body !== undefined),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError('Network error. Check your connection and retry.', 0, 'NETWORK');
  }
  if (!res.ok) throw await toApiError(res, fallback);
  return (await res.json()) as T;
}

function settingsBody(settings: Partial<ModuleSettings>): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (settings.durationSeconds !== undefined) body.duration_seconds = settings.durationSeconds ?? 0;
  if (settings.timerMode !== undefined) body.timer_mode = settings.timerMode;
  if (settings.shuffleQuestions !== undefined) body.shuffle_questions = settings.shuffleQuestions;
  return body;
}

export const libraryApi = {
  async listModules(includeArchived = false): Promise<AssessmentModule[]> {
    const rows = await request<TemplateSummaryDto[]>(
      `/library/templates${includeArchived ? '?include_archived=true' : ''}`,
      { fallback: 'Could not load the assessment library.' },
    );
    return rows.map(toAssessmentModule);
  },

  async getModule(moduleId: string): Promise<AssessmentModuleDetail> {
    const dto = await request<TemplateDetailDto>(`/library/templates/${moduleId}`, {
      fallback: 'Could not load this module.',
    });
    return toDetail(dto);
  },

  async createModule(input: ModuleCreateInput): Promise<AssessmentModuleDetail> {
    const dto = await request<TemplateDetailDto>('/library/templates', {
      method: 'POST',
      fallback: 'Could not create this module.',
      body: {
        title: input.title.trim(),
        category: input.moduleKind,
        assessment_category: input.moduleKind === 'psychometric' ? input.assessmentCategory : null,
        description: input.description.trim() || null,
        ...settingsBody(input.settings),
      },
    });
    return toDetail(dto);
  },

  async updateSettings(moduleId: string, settings: Partial<ModuleSettings>): Promise<AssessmentModuleDetail> {
    const dto = await request<TemplateDetailDto>(`/library/templates/${moduleId}`, {
      method: 'PUT',
      fallback: 'Could not save module settings.',
      body: settingsBody(settings),
    });
    return toDetail(dto);
  },

  async updateMetadata(
    moduleId: string,
    patch: { title?: string; description?: string; assessmentCategory?: AssessmentCategory },
  ): Promise<AssessmentModuleDetail> {
    const dto = await request<TemplateDetailDto>(`/library/templates/${moduleId}`, {
      method: 'PUT',
      fallback: 'Could not save module details.',
      body: {
        title: patch.title,
        description: patch.description,
        assessment_category: patch.assessmentCategory,
      },
    });
    return toDetail(dto);
  },

  async publishModule(moduleId: string): Promise<AssessmentModuleDetail> {
    const dto = await request<TemplateDetailDto>(`/library/templates/${moduleId}/publish`, {
      method: 'POST',
      fallback: 'Could not publish this module.',
    });
    return toDetail(dto);
  },

  async cloneVersion(moduleId: string): Promise<AssessmentModuleDetail> {
    const dto = await request<TemplateDetailDto>(`/library/templates/${moduleId}/clone-version`, {
      method: 'POST',
      fallback: 'Could not create a new version.',
    });
    return toDetail(dto);
  },

  async archiveModule(moduleId: string): Promise<AssessmentModuleDetail> {
    const dto = await request<TemplateDetailDto>(`/library/templates/${moduleId}/archive`, {
      method: 'POST',
      fallback: 'Could not archive this module.',
    });
    return toDetail(dto);
  },

  async createQuestion(moduleId: string, payload: QuestionPayload): Promise<TemplateQuestion> {
    return request<TemplateQuestion>(`/library/templates/${moduleId}/questions`, {
      method: 'POST',
      fallback: 'Could not save this question.',
      body: { payload },
    });
  },

  async updateQuestion(
    moduleId: string,
    questionId: string,
    payload: QuestionPayload,
  ): Promise<TemplateQuestion> {
    return request<TemplateQuestion>(`/library/templates/${moduleId}/questions/${questionId}`, {
      method: 'PUT',
      fallback: 'Could not save this question.',
      body: { payload },
    });
  },

  async deactivateQuestion(moduleId: string, questionId: string): Promise<TemplateQuestion> {
    return request<TemplateQuestion>(`/library/templates/${moduleId}/questions/${questionId}`, {
      method: 'DELETE',
      fallback: 'Could not remove this question.',
    });
  },

  async listCatalog(): Promise<CatalogModule[]> {
    const rows = await request<CatalogModuleDto[]>('/packages/modules', {
      fallback: 'Could not load published modules.',
    });
    return rows.map(toCatalogModule);
  },

  async previewPackage(
    moduleIds: string[],
    overrides?: Record<string, unknown[]>,
  ): Promise<RunnerTest[]> {
    return request<RunnerTest[]>('/packages/preview', {
      method: 'POST',
      fallback: 'Could not build the preview.',
      body: { module_ids: moduleIds, module_question_overrides: overrides ?? null },
    });
  },
};
