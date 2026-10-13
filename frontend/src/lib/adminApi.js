import { supabase } from './supabaseClient';
import { API_ORIGIN as API_BASE } from './api-origin';
import { ApiError } from './api-error';
import { apiFetch, BAD_RESPONSE_MESSAGE, requestJson } from './api-request';

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
 * @param {{ method?: string, body?: unknown, formData?: FormData }} [options]
 * @returns {Promise<any>}
 */
async function authedJson(path, fallback, { method = 'GET', body, formData } = {}) {
  const hasJson = body !== undefined;
  return requestJson(
    `${API_BASE}${path}`,
    {
      method,
      headers: await authHeaders(hasJson),
      body: formData ?? (hasJson ? JSON.stringify(body) : undefined),
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

// HR admin data access via supabase-js. RLS enforces tenant isolation, so these
// queries never need an explicit corporate_id filter.
export const adminApi = {
  async getPackages() {
    const { data, error } = await supabase
      .from('package_overview')
      .select('*')
      .order('created_at', { ascending: false });
    if (error) throw new Error(error.message);
    return data;
  },

  async createPackage({ title, description, tests }) {
    const { data, error } = await supabase.rpc('create_package', {
      p_title: title,
      p_description: description ?? '',
      p_tests: tests ?? [],
    });
    if (error) throw new Error(error.message);
    return data;
  },

  async getCandidates(packageId) {
    let query = supabase
      .from('candidate_overview')
      .select('*')
      .order('created_at', { ascending: false });
    if (packageId) query = query.eq('package_id', packageId);
    const { data, error } = await query;
    if (error) throw new Error(error.message);
    return data;
  },

  async getCorporate() {
    const { data, error } = await supabase.from('corporates').select('*').limit(1).maybeSingle();
    if (error) throw new Error(error.message);
    return data;
  },

  async updateCorporate(id, fields) {
    const { data, error } = await supabase
      .from('corporates')
      .update(fields)
      .eq('id', id)
      .select('*')
      .single();
    if (error) throw new Error(error.message);
    return data;
  },

  /**
   * Upload a corporate logo via FastAPI → Cloudflare R2.
   * Returns the public object URL (does not persist to Postgres).
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
    const blob = await res.blob();
    const reportType = res.headers.get('x-report-type') || '';
    const jdStatus = res.headers.get('x-jd-fit-status') || '';
    const isHtml = reportType === 'HTML' || (res.headers.get('content-type') || '').includes('text/html');
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `report-${candidateId}.${isHtml ? 'html' : 'pdf'}`;
    a.click();
    window.URL.revokeObjectURL(url);
    return { isHtml, jdStatus };
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

  async getCandidateScorecard(candidateId) {
    const { data: candidate, error: candErr } = await supabase
      .from('candidate_overview')
      .select('*')
      .eq('id', candidateId)
      .maybeSingle();
    if (candErr) throw new Error(candErr.message);
    if (!candidate) throw new Error('Candidate not found');

    const [evalRes, assessRes, respRes, progRes] = await Promise.all([
      supabase
        .from('candidate_evaluations')
        .select('payload, overall_fit, generated_at')
        .eq('candidate_id', candidateId)
        .maybeSingle(),
      supabase
        .from('assessments')
        .select('id, title, position, questions')
        .eq('package_id', candidate.package_id)
        .order('position'),
      supabase
        .from('candidate_responses')
        .select('assessment_id, question_id, response')
        .eq('candidate_id', candidateId),
      supabase
        .from('candidate_progress')
        .select('assessment_id, status, score, completed_at')
        .eq('candidate_id', candidateId),
    ]);

    for (const result of [evalRes, assessRes, respRes, progRes]) {
      if (result.error) throw new Error(result.error.message);
    }

    return {
      candidate,
      evaluation: evalRes.data,
      assessments: assessRes.data || [],
      responses: respRes.data || [],
      progress: progRes.data || [],
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

  async createCompany({ name, slug, contactEmail }) {
    return authedJson('/api/v1/admin/companies', 'Failed to create company', {
      method: 'POST',
      body: {
        name,
        slug: slug || undefined,
        contact_email: contactEmail || undefined,
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

  async updateAdminPackage(packageId, body) {
    return authedJson(`/api/v1/admin/packages/${packageId}`, 'Failed to update package', {
      method: 'PUT',
      body,
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

  async listCorporates() {
    const rows = await authedJson('/api/v1/packages/corporates', 'Failed to load companies');
    return expectArray(rows, 'packages/corporates');
  },

  async getDraftPackage(packageId) {
    return authedJson(`/api/v1/packages/drafts/${packageId}`, 'Failed to load draft');
  },

  async saveDraftPackage(body, packageId) {
    const path = packageId ? `/api/v1/packages/drafts/${packageId}` : '/api/v1/packages/drafts';
    return authedJson(path, 'Failed to save draft', {
      method: packageId ? 'PUT' : 'POST',
      body,
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
  const headers = ['Name', 'Email', 'Package', 'Status', 'Progress', 'Avg Score', 'JD Fit'];
  const escape = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const rows = candidates.map((c) => [
    c.full_name,
    c.email,
    c.package_title,
    candidateStatus(c),
    `${c.completed_assessments}/${c.total_assessments}`,
    c.avg_score != null ? `${c.avg_score}%` : '-',
    c.jd_fit != null ? `${c.jd_fit}%` : '-',
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
