import { supabase } from '../../../lib/supabaseClient';
import {
  DEFAULT_CONFIDENTIALITY_NOTICE_TEXT,
  DEFAULT_TOP_DISCLAIMER_TEXT,
} from '../types/module';
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
import { isLikertOptionsForbiddenDetail, toLegacyLikertWirePayload } from '../types/question';
import { API_ORIGIN as API_BASE } from '../../../lib/api-origin';
import { ApiError } from '../../../lib/api-error';
import { requestJson } from '../../../lib/api-request';

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
  show_top_disclaimer?: boolean;
  top_disclaimer_text?: string | null;
  show_confidentiality_notice?: boolean;
  confidentiality_notice_text?: string | null;
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
  show_top_disclaimer?: boolean;
  top_disclaimer_text?: string | null;
  show_confidentiality_notice?: boolean;
  confidentiality_notice_text?: string | null;
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
  scale_values?: number[] | null;
  show_disclaimer?: boolean;
  disclaimer_text?: string | null;
}

export interface RunnerTest {
  id: string;
  title: string;
  description: string | null;
  module_kind?: ModuleKind;
  time_limit_minutes: number | null;
  duration_seconds: number | null;
  timer_mode: TimerMode;
  shuffle_questions: boolean;
  show_top_disclaimer?: boolean;
  top_disclaimer_text?: string | null;
  show_confidentiality_notice?: boolean;
  confidentiality_notice_text?: string | null;
  started_at: string | null;
  /** Immutable display deadline (ISO UTC); null when untimed / not started. */
  expires_at?: string | null;
  /** Write-lock deadline (expires_at + grace); null when untimed / not started. */
  write_expires_at?: string | null;
  /** Server UTC clock for client offset sync. */
  server_now?: string | null;
  /** Server-computed display countdown seed (UTC); null when untimed. */
  remaining_seconds?: number | null;
  /** Seconds until write lock (duration + grace); expire / auto-submit seed. */
  write_remaining_seconds?: number | null;
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
    showTopDisclaimer: dto.show_top_disclaimer ?? false,
    topDisclaimerText: dto.top_disclaimer_text ?? DEFAULT_TOP_DISCLAIMER_TEXT,
    showConfidentialityNotice: dto.show_confidentiality_notice ?? false,
    confidentialityNoticeText: dto.confidentiality_notice_text ?? DEFAULT_CONFIDENTIALITY_NOTICE_TEXT,
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
    showTopDisclaimer: dto.show_top_disclaimer ?? false,
    topDisclaimerText: dto.top_disclaimer_text ?? DEFAULT_TOP_DISCLAIMER_TEXT,
    showConfidentialityNotice: dto.show_confidentiality_notice ?? false,
    confidentialityNoticeText: dto.confidentiality_notice_text ?? DEFAULT_CONFIDENTIALITY_NOTICE_TEXT,
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
  return requestJson<T>(
    `${API_BASE}/api/v1${path}`,
    {
      method,
      headers: await authHeaders(body !== undefined),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    },
    fallback,
  );
}

function settingsBody(settings: Partial<ModuleSettings>): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (settings.durationSeconds !== undefined) body.duration_seconds = settings.durationSeconds ?? 0;
  if (settings.timerMode !== undefined) body.timer_mode = settings.timerMode;
  if (settings.shuffleQuestions !== undefined) body.shuffle_questions = settings.shuffleQuestions;
  if (settings.showTopDisclaimer !== undefined) body.show_top_disclaimer = settings.showTopDisclaimer;
  if (settings.topDisclaimerText !== undefined)
    body.top_disclaimer_text = settings.topDisclaimerText.trim() || DEFAULT_TOP_DISCLAIMER_TEXT;
  if (settings.showConfidentialityNotice !== undefined)
    body.show_confidentiality_notice = settings.showConfidentialityNotice;
  if (settings.confidentialityNoticeText !== undefined)
    body.confidentiality_notice_text =
      settings.confidentialityNoticeText.trim() || DEFAULT_CONFIDENTIALITY_NOTICE_TEXT;
  return body;
}

/**
 * Wire payload for library create/update.
 *
 * Live api-qa still validates Likert with the pre-dynamic schema (``scale_labels``
 * only; ``options`` / ``scale_points`` are ``extra_forbidden``). Prefer that shape
 * on the wire; newer backends still accept it via ``coerce_likert_options``.
 * If a newer API instead rejects the legacy shape, retry with the full payload.
 *
 * @param payload - Normalized editor payload.
 * @returns Body ``payload`` value for the HTTP request.
 */
function toWireQuestionPayload(payload: QuestionPayload): QuestionPayload | ReturnType<typeof toLegacyLikertWirePayload> {
  if (payload.type === 'likert') return toLegacyLikertWirePayload(payload);
  return payload;
}

/**
 * Persist a builder question, with Likert wire-shape compatibility for stale APIs.
 *
 * @param path - Library questions collection or item path.
 * @param method - ``POST`` (create) or ``PUT`` (update).
 * @param payload - Normalized editor payload.
 * @returns Saved template question row.
 */
async function saveTemplateQuestion(
  path: string,
  method: 'POST' | 'PUT',
  payload: QuestionPayload,
): Promise<TemplateQuestion> {
  const wirePayload = toWireQuestionPayload(payload);
  try {
    return await request<TemplateQuestion>(path, {
      method,
      fallback: 'Could not save this question.',
      body: { payload: wirePayload },
    });
  } catch (err) {
    const detail = err instanceof ApiError ? err.detail : null;
    const canRetryFull =
      payload.type === 'likert' &&
      err instanceof ApiError &&
      err.status === 422 &&
      !isLikertOptionsForbiddenDetail(detail);
    if (!canRetryFull) throw err;
    return request<TemplateQuestion>(path, {
      method,
      fallback: 'Could not save this question.',
      body: { payload },
    });
  }
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
    return saveTemplateQuestion(`/library/templates/${moduleId}/questions`, 'POST', payload);
  },

  async updateQuestion(
    moduleId: string,
    questionId: string,
    payload: QuestionPayload,
  ): Promise<TemplateQuestion> {
    return saveTemplateQuestion(
      `/library/templates/${moduleId}/questions/${questionId}`,
      'PUT',
      payload,
    );
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
