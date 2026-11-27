import { supabase } from './supabaseClient';
import { API_ORIGIN as API_BASE } from './api-origin';
import { ApiError } from './api-error';
import { apiFetch, BAD_RESPONSE_MESSAGE, requestJson } from './api-request';
import { saveReportResponse } from './download-response';

/**
 * Build FastAPI auth headers from the HR user's Supabase session.
 *
 * @param {boolean} json Whether the request carries a JSON body.
 * @returns {Promise<Record<string, string>>}
 */
async function authHeaders(json) {
  const { data: { session } } = await supabase.auth.getSession();
  const headers = { Authorization: `Bearer ${session?.access_token ?? ''}` };
  if (json) headers['Content-Type'] = 'application/json';
  return headers;
}

/**
 * Authenticated JSON call to the FastAPI service. Network failures, error
 * statuses, and non-JSON bodies all reject with an `ApiError`.
 *
 * @param {string} path Path starting with `/api`.
 * @param {string} fallback Message used when the error body carries nothing readable.
 * @param {{ method?: string, body?: unknown, formData?: FormData, signal?: AbortSignal }} [options]
 * @returns {Promise<any>}
 */
async function authedJson(path, fallback, { method = 'GET', body, formData, signal } = {}) {
  const hasJson = body !== undefined;
  return requestJson(
    `${API_BASE}${path}`,
    {
      method,
      headers: await authHeaders(hasJson),
      body: formData ?? (hasJson ? JSON.stringify(body) : undefined),
      signal,
    },
    fallback,
  );
}

/**
 * @param {unknown} rows
 * @param {string} resource Used in the error detail only.
 * @returns {any[]}
 */
function expectArray(rows, resource) {
  if (!Array.isArray(rows)) {
    throw new ApiError(BAD_RESPONSE_MESSAGE, 200, 'BAD_RESPONSE', `${resource}: expected array`);
  }
  return rows;
}

// Ops console data access. All table/view reads go through ops-authenticated
// FastAPI endpoints; supabase-js is only used for the auth session.
export const adminApi = {
  /** `package_overview` rows across companies, newest first. */
  async getPackages() {
    const rows = await authedJson('/api/v1/admin/packages', 'Failed to load assessment suites');
    return expectArray(rows, 'admin/packages');
  },

  /**
   * Candidate overview rows via the ops-authenticated FastAPI endpoint. The
   * `candidate_overview` view is security_invoker over `candidate_progress`,
   * which the ops console cannot read through PostgREST.
   * @param {string} [packageId]
   */
  async getCandidates(packageId) {
    const qs = packageId ? `?package_id=${encodeURIComponent(packageId)}` : '';
    const rows = await authedJson(`/api/v1/admin/candidates${qs}`, 'Failed to load candidates');
    return expectArray(rows, 'admin/candidates');
  },

  /**
   * Full `corporates` row. Resolves to null when no company id is known yet.
   * @param {string | null | undefined} corporateId
   */
  async getCorporate(corporateId) {
    if (!corporateId) return null;
    return authedJson(
      `/api/v1/admin/corporates/${encodeURIComponent(corporateId)}`,
      'Failed to load company',
    );
  },

  /**
   * Update branding/contact fields; returns the full updated row.
   * @param {string} id
   * @param {{ logo_url?: string | null, primary_color?: string | null, contact_email?: string | null, contact_phone?: string | null }} fields
   */
  async updateCorporate(id, fields) {
    return authedJson(
      `/api/v1/admin/corporates/${encodeURIComponent(id)}`,
      'Failed to save company',
      { method: 'PATCH', body: fields },
    );
  },

  /**
   * Upload a corporate logo via FastAPI → Cloudflare R2.
   * Backend persists ``corporates.logo_url`` and returns the public object URL.
   */
  async uploadCorporateLogo(corporateId, file) {
    const formData = new FormData();
    formData.append('file', file);
    const payload = await authedJson(`/api/v1/corporates/${corporateId}/logo`, 'Logo upload failed', {
      method: 'POST',
      formData,
    });
    return payload.logo_url || payload.url;
  },

  // Report generation stays in the FastAPI service (WeasyPrint + service_role).
  // We authenticate the request with the HR user's Supabase access token.
  async downloadReport(candidateId) {
    const res = await apiFetch(
      `${API_BASE}/api/v1/admin/candidates/${candidateId}/report`,
      { headers: await authHeaders(false) },
      'Failed to download report',
    );
    return saveReportResponse(res, `MindQ Report - ${candidateId}`);
  },

  async inviteCandidate({ candidateEmail, packageId, corporateId }) {
    return authedJson('/api/candidates/invite', 'Invite failed', {
      method: 'POST',
      body: {
        candidate_email: candidateEmail,
        package_id: packageId,
        corporate_id: corporateId,
      },
    });
  },

  /**
   * Candidate scorecard via the ops-authenticated FastAPI endpoint (same
   * server-side pattern as `getCandidates`).
   * @param {string} candidateId
   * @returns {Promise<{candidate: any, evaluation: any, assessments: any[], responses: any[], progress: any[]}>}
   */
  async getCandidateScorecard(candidateId) {
    const payload = await authedJson(
      `/api/v1/admin/candidates/${encodeURIComponent(candidateId)}/scorecard`,
      'Failed to load candidate',
    );
    if (!payload || typeof payload !== 'object' || !payload.candidate) {
      throw new ApiError(BAD_RESPONSE_MESSAGE, 200, 'BAD_RESPONSE', 'admin/scorecard: missing candidate');
    }
    return {
      candidate: payload.candidate,
      evaluation: payload.evaluation ?? null,
      assessments: expectArray(payload.assessments ?? [], 'admin/scorecard.assessments'),
      responses: expectArray(payload.responses ?? [], 'admin/scorecard.responses'),
      progress: expectArray(payload.progress ?? [], 'admin/scorecard.progress'),
    };
  },

  publicTrackUrl(trackSecret) {
    if (!trackSecret) return '';
    return `${window.location.origin}/public/track/${encodeURIComponent(trackSecret)}`;
  },

  /**
   * Generate an assessment blueprint from a JD via FastAPI + Gemini.
   * Returns AssessmentPackageBlueprint JSON for preview before save.
   */
  async generatePackageFromJd({ role, jobDescription, seniority, questionCount = 10 }) {
    return authedJson('/api/v1/packages/generate', 'Assessment generation failed', {
      method: 'POST',
      body: {
        role,
        job_description: jobDescription,
        seniority,
        question_count: questionCount,
      },
    });
  },

  /**
   * Extract JD text from a PDF via FastAPI (pypdf, in-memory, nothing stored).
   * Returns { text, page_count, char_count, truncated } for the builder's
   * Role Assessment Brief. Scanned / image-only PDFs reject with a 422 message.
   */
  async extractJdFromPdf(file) {
    const formData = new FormData();
    formData.append('file', file);
    return authedJson('/api/v1/packages/jd/extract-pdf', 'Could not read that PDF', {
      method: 'POST',
      formData,
    });
  },

  async listGlobalModules() {
    const rows = await authedJson('/api/v1/packages/modules', 'Failed to load modules');
    return expectArray(rows, 'packages/modules');
  },

  async _libraryFetch(path, { method = 'GET', body } = {}) {
    return authedJson(`/api/v1/library${path}`, 'Library request failed', { method, body });
  },

  async listTemplates() {
    return this._libraryFetch('/templates');
  },

  async getTemplate(templateId) {
    return this._libraryFetch(`/templates/${templateId}`);
  },

  async createTemplate(body) {
    return this._libraryFetch('/templates', { method: 'POST', body });
  },

  async updateTemplate(templateId, body) {
    return this._libraryFetch(`/templates/${templateId}`, { method: 'PUT', body });
  },

  async archiveTemplate(templateId) {
    return this._libraryFetch(`/templates/${templateId}/archive`, { method: 'POST' });
  },

  async createTemplateQuestion(templateId, body) {
    return this._libraryFetch(`/templates/${templateId}/questions`, {
      method: 'POST',
      body,
    });
  },

  async updateTemplateQuestion(templateId, questionId, body) {
    return this._libraryFetch(`/templates/${templateId}/questions/${questionId}`, {
      method: 'PUT',
      body,
    });
  },

  async deactivateTemplateQuestion(templateId, questionId) {
    return this._libraryFetch(`/templates/${templateId}/questions/${questionId}`, {
      method: 'DELETE',
    });
  },

  async syncQuestionToMaster(templateId, body) {
    return this._libraryFetch(`/templates/${templateId}/sync-question`, {
      method: 'POST',
      body,
    });
  },

  async addTemplateToPackage(packageId, templateId) {
    return authedJson(`/api/v1/packages/${packageId}/add-template`, 'Failed to add template', {
      method: 'POST',
      body: { template_id: templateId },
    });
  },

  async createCompany({ name, slug, contactEmail, allowedHrEmails }) {
    return authedJson('/api/v1/admin/companies', 'Failed to create company', {
      method: 'POST',
      body: {
        name,
        slug: slug || undefined,
        contact_email: contactEmail || undefined,
        allowed_hr_emails: allowedHrEmails || [],
      },
    });
  },

  /**
   * Ops-only partial update. Pass `contact_email: ''` to clear the HR email.
   */
  async updateCompany(companyId, fields) {
    return authedJson(`/api/v1/admin/companies/${companyId}`, 'Failed to update company', {
      method: 'PATCH',
      body: fields,
    });
  },

  /**
   * Ops-only soft delete: hides the company from active views, keeps records.
   */
  async deleteCompany(companyId) {
    return authedJson(`/api/v1/admin/companies/${companyId}`, 'Failed to delete company', {
      method: 'DELETE',
    });
  },

  /**
   * Ops-only logo upload to R2. The backend persists `logo_url` on the row.
   */
  async uploadCompanyLogo(companyId, file) {
    const formData = new FormData();
    formData.append('file', file);
    const data = await authedJson(`/api/v1/admin/companies/${companyId}/logo`, 'Logo upload failed', {
      method: 'POST',
      formData,
    });
    return data.logo_url;
  },

  async getAdminPackage(packageId) {
    return authedJson(`/api/v1/admin/packages/${packageId}`, 'Failed to load package');
  },

  /**
   * Soft-archive a published suite (or hard-delete a draft). Candidate records stay.
   * @param {string} packageId
   * @returns {Promise<{id: string, status: 'archived' | 'deleted'}>}
   */
  async deletePackage(packageId) {
    return authedJson(`/api/v1/admin/packages/${packageId}`, 'Failed to delete package', {
      method: 'DELETE',
    });
  },

  /**
   * @param {string} packageId
   * @param {unknown} body
   * @param {{ signal?: AbortSignal }} [options]
   */
  async updateAdminPackage(packageId, body, { signal } = {}) {
    return authedJson(`/api/v1/admin/packages/${packageId}`, 'Failed to update package', {
      method: 'PUT',
      body,
      signal,
    });
  },

  /**
   * Change a package deadline (works on published packages).
   * @param {string} packageId
   * @param {string | null} closeTime ISO 8601 with offset, or null to remove the deadline.
   * @returns {Promise<{id: string, open_time: string | null, close_time: string | null}>}
   */
  async updatePackageSchedule(packageId, closeTime) {
    return authedJson(`/api/v1/admin/packages/${packageId}/schedule`, 'Failed to update deadline', {
      method: 'PATCH',
      body: { close_time: closeTime },
    });
  },

  async listCorporatePackages(corporateId) {
    const rows = await authedJson(
      `/api/v1/packages?corporate_id=${encodeURIComponent(corporateId)}`,
      'Failed to load packages',
    );
    return expectArray(rows, 'packages');
  },

  /**
   * Email candidate + HR access for a published package. Blank recipient falls back
   * to the corporate HR email server-side. Also enables open enrollment.
   */
  async sharePackage(packageId, { recipientEmail } = {}) {
    return authedJson(`/api/v1/packages/${packageId}/share`, 'Failed to send invite email', {
      method: 'POST',
      body: { recipient_email: recipientEmail || null },
    });
  },

  /**
   * Bulk-invite candidates to a published package. Each new email gets a unique PIN.
   *
   * @param {string} packageId
   * @param {string[]} emails
   */
  async bulkInviteCandidates(packageId, emails) {
    return authedJson(
      `/api/v1/packages/${packageId}/candidates/bulk`,
      'Failed to send candidate invites',
      {
        method: 'POST',
        body: { emails },
      },
    );
  },

  async listCorporates() {
    const rows = await authedJson('/api/v1/packages/corporates', 'Failed to load companies');
    return expectArray(rows, 'packages/corporates');
  },

  async getDraftPackage(packageId) {
    return authedJson(`/api/v1/packages/drafts/${packageId}`, 'Failed to load draft');
  },

  /**
   * @param {unknown} body
   * @param {string | null} packageId
   * @param {{ signal?: AbortSignal }} [options]
   */
  async saveDraftPackage(body, packageId, { signal } = {}) {
    const path = packageId ? `/api/v1/packages/drafts/${packageId}` : '/api/v1/packages/drafts';
    return authedJson(path, 'Failed to save draft', {
      method: packageId ? 'PUT' : 'POST',
      body,
      signal,
    });
  },

  async publishDraftPackage(packageId) {
    return authedJson(`/api/v1/packages/drafts/${packageId}/publish`, 'Failed to publish package', {
      method: 'POST',
    });
  },

  async saveGeneratedPackage({ blueprint, jobDescription }) {
    return authedJson('/api/v1/packages/save', 'Failed to save package', {
      method: 'POST',
      body: {
        blueprint,
        job_description: jobDescription ?? '',
      },
    });
  },

  // HR-triggered reminder email (FastAPI service, authenticated with HR token).
  async nudgeCandidate(candidateId) {
    return authedJson(`/api/v1/admin/candidates/${candidateId}/nudge`, 'Failed to send reminder', {
      method: 'POST',
    });
  },

  /** Wipe responses/progress/evaluations so the candidate can retake. */
  async resetCandidateAssessment(candidateId) {
    return authedJson(
      `/api/v1/admin/candidates/${candidateId}/reset`,
      'Failed to reset assessment',
      { method: 'POST' },
    );
  },

  /** Soft-delete a candidate (ops). Historical rows stay in the database. */
  async softDeleteCandidate(candidateId) {
    return authedJson(
      `/api/v1/admin/candidates/${candidateId}/soft-delete`,
      'Failed to delete candidate',
      { method: 'POST' },
    );
  },

  /**
   * Provision an HR user for a company via Supabase Auth Admin invite.
   * @param {string} companyId
   * @param {string} email
   */
  async inviteHr(companyId, email) {
    return authedJson(`/api/v1/admin/companies/${companyId}/invite-hr`, 'Failed to send HR access', {
      method: 'POST',
      body: { email },
    });
  },

  /**
   * Technical-only report payload for client-side PDF export.
   * @param {string} candidateId
   */
  async getReportData(candidateId) {
    return authedJson(`/api/v1/candidates/${candidateId}/report-data`, 'Failed to load report data');
  },
};

// Client-side CSV export of the (already RLS-scoped) candidate overview rows.
export function exportCandidatesCsv(candidates) {
  const headers = ['Name', 'Email', 'Package', 'Status', 'Progress', 'Avg Score'];
  const escape = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const rows = candidates.map((c) => [
    c.full_name,
    c.email,
    c.package_title,
    candidateStatus(c),
    `${c.completed_assessments}/${c.total_assessments}`,
    c.avg_score != null ? `${c.avg_score}%` : '-',
  ].map(escape).join(','));
  const csv = [headers.map(escape).join(','), ...rows].join('\n');

  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `candidates-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  window.URL.revokeObjectURL(url);
}

// Derive a coarse status label from the overview counts.
export function candidateStatus(c) {
  if (c.total_assessments > 0 && c.completed_assessments >= c.total_assessments) return 'completed';
  if (c.completed_assessments > 0 || c.logged_in_at) return 'in_progress';
  return 'not_started';
}

export function maskEmail(email) {
  if (!email || !email.includes('@')) return '—';
  const [local, domain] = email.split('@');
  const visible = local.slice(0, 2);
  return `${visible}${'•'.repeat(Math.max(1, local.length - 2))}@${domain}`;
}

export function maskAccessCode(code) {
  if (!code) return '—';
  if (code.length <= 4) return '••••';
  return `${code.slice(0, 3)}••••${code.slice(-1)}`;
}
