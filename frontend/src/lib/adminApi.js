import { supabase } from './supabaseClient';

const API_BASE = import.meta.env.VITE_API_URL || '';

/**
 * Extract a human-readable message from a FastAPI error response.
 * Handles both `{detail: string}` and 422 `{detail: [{msg}]}` shapes.
 *
 * @param {Response} res
 * @param {string} fallback
 * @returns {Promise<string>}
 */
async function readErrorDetail(res, fallback) {
  try {
    const payload = await res.json();
    const detail = payload?.detail;
    if (typeof detail === 'string' && detail) return detail;
    if (Array.isArray(detail) && detail[0]?.msg) {
      return String(detail[0].msg).replace(/^Value error, /, '');
    }
  } catch {
    /* non-JSON body */
  }
  return fallback;
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
    const { data: { session } } = await supabase.auth.getSession();
    const body = new FormData();
    body.append('file', file);
    const res = await fetch(`${API_BASE}/api/v1/corporates/${corporateId}/logo`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${session?.access_token ?? ''}` },
      body,
    });
    if (!res.ok) {
      let detail = 'Logo upload failed';
      try {
        const payload = await res.json();
        detail = payload?.detail || detail;
      } catch {
        /* ignore */
      }
      throw new Error(typeof detail === 'string' ? detail : 'Logo upload failed');
    }
    const payload = await res.json();
    return payload.logo_url || payload.url;
  },

  // Report generation stays in the FastAPI service (WeasyPrint + service_role).
  // We authenticate the request with the HR user's Supabase access token.
  async downloadReport(candidateId) {
    const { data: { session } } = await supabase.auth.getSession();
    const res = await fetch(`${API_BASE}/api/v1/admin/candidates/${candidateId}/report`, {
      headers: { Authorization: `Bearer ${session?.access_token ?? ''}` },
    });
    if (!res.ok) throw new Error('Failed to download report');
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
    const { data: { session } } = await supabase.auth.getSession();
    const res = await fetch(`${API_BASE}/api/candidates/invite`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${session?.access_token ?? ''}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        candidate_email: candidateEmail,
        package_id: packageId,
        corporate_id: corporateId,
      }),
    });
    if (!res.ok) {
      let detail = 'Invite failed';
      try {
        const payload = await res.json();
        detail = payload?.detail || detail;
      } catch {
        /* ignore */
      }
      throw new Error(typeof detail === 'string' ? detail : 'Invite failed');
    }
    return res.json();
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
    const { data: { session } } = await supabase.auth.getSession();
    const res = await fetch(`${API_BASE}/api/v1/packages/generate`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${session?.access_token ?? ''}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        role,
        job_description: jobDescription,
        seniority,
        question_count: questionCount,
      }),
    });
    if (!res.ok) {
      let detail = 'Assessment generation failed';
      try {
        const payload = await res.json();
        detail = payload?.detail || detail;
      } catch {
        /* ignore */
      }
      throw new Error(typeof detail === 'string' ? detail : 'Assessment generation failed');
    }
    return res.json();
  },

  /**
   * Persist an approved generated blueprint under the HR tenant (packages + assessments).
   */
  async listGlobalModules() {
    const { data: { session } } = await supabase.auth.getSession();
    const res = await fetch(`${API_BASE}/api/v1/packages/modules`, {
      headers: { Authorization: `Bearer ${session?.access_token ?? ''}` },
    });
    if (!res.ok) {
      let detail = 'Failed to load modules';
      try {
        const payload = await res.json();
        detail = payload?.detail || detail;
      } catch {
        /* ignore */
      }
      throw new Error(typeof detail === 'string' ? detail : 'Failed to load modules');
    }
    return res.json();
  },

  async _libraryFetch(path, { method = 'GET', body } = {}) {
    const { data: { session } } = await supabase.auth.getSession();
    const res = await fetch(`${API_BASE}/api/v1/library${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${session?.access_token ?? ''}`,
        ...(body != null ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body != null ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      let detail = `Library request failed (${res.status})`;
      try {
        const payload = await res.json();
        detail = payload?.detail || detail;
      } catch {
        /* ignore */
      }
      const error = new Error(typeof detail === 'string' ? detail : 'Library request failed');
      error.status = res.status;
      throw error;
    }
    if (res.status === 204) return null;
    return res.json();
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
    const { data: { session } } = await supabase.auth.getSession();
    const res = await fetch(`${API_BASE}/api/v1/packages/${packageId}/add-template`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${session?.access_token ?? ''}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ template_id: templateId }),
    });
    if (!res.ok) {
      let detail = 'Failed to add template to package';
      try {
        const payload = await res.json();
        detail = payload?.detail || detail;
      } catch {
        /* ignore */
      }
      throw new Error(typeof detail === 'string' ? detail : 'Failed to add template');
    }
    return res.json();
  },

  async createCompany({ name, slug, contactEmail }) {
    const { data: { session } } = await supabase.auth.getSession();
    const res = await fetch(`${API_BASE}/api/v1/admin/companies`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${session?.access_token ?? ''}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        name,
        slug: slug || undefined,
        contact_email: contactEmail || undefined,
      }),
    });
    if (!res.ok) {
      throw new Error(await readErrorDetail(res, 'Failed to create company'));
    }
    return res.json();
  },

  /**
   * Ops-only partial update. Pass `contact_email: ''` to clear the HR email.
   */
  async updateCompany(companyId, fields) {
    const { data: { session } } = await supabase.auth.getSession();
    const res = await fetch(`${API_BASE}/api/v1/admin/companies/${companyId}`, {
      method: 'PATCH',
      headers: {
        Authorization: `Bearer ${session?.access_token ?? ''}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(fields),
    });
    if (!res.ok) {
      throw new Error(await readErrorDetail(res, 'Failed to update company'));
    }
    return res.json();
  },

  /**
   * Ops-only logo upload to R2. The backend persists `logo_url` on the row.
   */
  async uploadCompanyLogo(companyId, file) {
    const { data: { session } } = await supabase.auth.getSession();
    const body = new FormData();
    body.append('file', file);
    const res = await fetch(`${API_BASE}/api/v1/admin/companies/${companyId}/logo`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${session?.access_token ?? ''}` },
      body,
    });
    if (!res.ok) {
      throw new Error(await readErrorDetail(res, 'Logo upload failed'));
    }
    const data = await res.json();
    return data.logo_url;
  },

  async getAdminPackage(packageId) {
    const { data: { session } } = await supabase.auth.getSession();
    const res = await fetch(`${API_BASE}/api/v1/admin/packages/${packageId}`, {
      headers: { Authorization: `Bearer ${session?.access_token ?? ''}` },
    });
    if (!res.ok) {
      let detail = 'Failed to load package';
      try {
        const payload = await res.json();
        detail = payload?.detail || detail;
      } catch {
        /* ignore */
      }
      throw new Error(typeof detail === 'string' ? detail : 'Failed to load package');
    }
    return res.json();
  },

  async updateAdminPackage(packageId, body) {
    const { data: { session } } = await supabase.auth.getSession();
    const res = await fetch(`${API_BASE}/api/v1/admin/packages/${packageId}`, {
      method: 'PUT',
      headers: {
        Authorization: `Bearer ${session?.access_token ?? ''}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      let detail = 'Failed to update package';
      try {
        const payload = await res.json();
        detail = payload?.detail || detail;
      } catch {
        /* ignore */
      }
      throw new Error(typeof detail === 'string' ? detail : 'Failed to update package');
    }
    return res.json();
  },

  /**
   * Change a package deadline (works on published packages).
   * @param {string} packageId
   * @param {string | null} closeTime ISO 8601 with offset, or null to remove the deadline.
   * @returns {Promise<{id: string, open_time: string | null, close_time: string | null}>}
   */
  async updatePackageSchedule(packageId, closeTime) {
    const { data: { session } } = await supabase.auth.getSession();
    const res = await fetch(`${API_BASE}/api/v1/admin/packages/${packageId}/schedule`, {
      method: 'PATCH',
      headers: {
        Authorization: `Bearer ${session?.access_token ?? ''}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ close_time: closeTime }),
    });
    if (!res.ok) {
      throw new Error(await readErrorDetail(res, 'Failed to update deadline'));
    }
    return res.json();
  },

  async listCorporatePackages(corporateId) {
    const { data: { session } } = await supabase.auth.getSession();
    const res = await fetch(
      `${API_BASE}/api/v1/packages?corporate_id=${encodeURIComponent(corporateId)}`,
      { headers: { Authorization: `Bearer ${session?.access_token ?? ''}` } },
    );
    if (!res.ok) {
      throw new Error(await readErrorDetail(res, 'Failed to load packages'));
    }
    return res.json();
  },

  /**
   * Email candidate + HR access for a published package. Blank recipient falls back
   * to the corporate HR email server-side. Also enables open enrollment.
   */
  async sharePackage(packageId, { recipientEmail } = {}) {
    const { data: { session } } = await supabase.auth.getSession();
    const res = await fetch(`${API_BASE}/api/v1/packages/${packageId}/share`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${session?.access_token ?? ''}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ recipient_email: recipientEmail || null }),
    });
    if (!res.ok) {
      throw new Error(await readErrorDetail(res, 'Failed to send invite email'));
    }
    return res.json();
  },

  async listCorporates() {
    const { data: { session } } = await supabase.auth.getSession();
    const res = await fetch(`${API_BASE}/api/v1/packages/corporates`, {
      headers: { Authorization: `Bearer ${session?.access_token ?? ''}` },
    });
    if (!res.ok) {
      let detail = 'Failed to load companies';
      try {
        const payload = await res.json();
        detail = payload?.detail || detail;
      } catch {
        /* ignore */
      }
      throw new Error(typeof detail === 'string' ? detail : 'Failed to load companies');
    }
    return res.json();
  },

  async getDraftPackage(packageId) {
    const { data: { session } } = await supabase.auth.getSession();
    const res = await fetch(`${API_BASE}/api/v1/packages/drafts/${packageId}`, {
      headers: { Authorization: `Bearer ${session?.access_token ?? ''}` },
    });
    if (!res.ok) {
      let detail = 'Failed to load draft';
      try {
        const payload = await res.json();
        detail = payload?.detail || detail;
      } catch {
        /* ignore */
      }
      throw new Error(typeof detail === 'string' ? detail : 'Failed to load draft');
    }
    return res.json();
  },

  async saveDraftPackage(body, packageId) {
    const { data: { session } } = await supabase.auth.getSession();
    const url = packageId
      ? `${API_BASE}/api/v1/packages/drafts/${packageId}`
      : `${API_BASE}/api/v1/packages/drafts`;
    const res = await fetch(url, {
      method: packageId ? 'PUT' : 'POST',
      headers: {
        Authorization: `Bearer ${session?.access_token ?? ''}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      let detail = 'Failed to save draft';
      try {
        const payload = await res.json();
        detail = payload?.detail || detail;
      } catch {
        /* ignore */
      }
      throw new Error(typeof detail === 'string' ? detail : 'Failed to save draft');
    }
    return res.json();
  },

  async publishDraftPackage(packageId) {
    const { data: { session } } = await supabase.auth.getSession();
    const res = await fetch(`${API_BASE}/api/v1/packages/drafts/${packageId}/publish`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${session?.access_token ?? ''}` },
    });
    if (!res.ok) {
      let detail = 'Failed to publish package';
      try {
        const payload = await res.json();
        detail = payload?.detail || detail;
      } catch {
        /* ignore */
      }
      throw new Error(typeof detail === 'string' ? detail : 'Failed to publish package');
    }
    return res.json();
  },

  async saveGeneratedPackage({ blueprint, jobDescription }) {
    const { data: { session } } = await supabase.auth.getSession();
    const res = await fetch(`${API_BASE}/api/v1/packages/save`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${session?.access_token ?? ''}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        blueprint,
        job_description: jobDescription ?? '',
      }),
    });
    if (!res.ok) {
      let detail = 'Failed to save package';
      try {
        const payload = await res.json();
        detail = payload?.detail || detail;
      } catch {
        /* ignore */
      }
      throw new Error(typeof detail === 'string' ? detail : 'Failed to save package');
    }
    return res.json();
  },

  // HR-triggered reminder email (FastAPI service, authenticated with HR token).
  async nudgeCandidate(candidateId) {
    const { data: { session } } = await supabase.auth.getSession();
    const res = await fetch(`${API_BASE}/api/v1/admin/candidates/${candidateId}/nudge`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${session?.access_token ?? ''}` },
    });
    if (!res.ok) throw new Error('Failed to send reminder');
    return res.json();
  },

  /**
   * Provision an HR user for a company via Supabase Auth Admin invite.
   * @param {string} companyId
   * @param {string} email
   */
  async inviteHr(companyId, email) {
    const { data: { session } } = await supabase.auth.getSession();
    const res = await fetch(
      `${API_BASE}/api/v1/admin/companies/${companyId}/invite-hr`,
      {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${session?.access_token ?? ''}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email }),
      },
    );
    if (!res.ok) {
      let detail = 'Failed to send HR access';
      try {
        const payload = await res.json();
        detail = payload?.detail || detail;
      } catch {
        /* ignore */
      }
      throw new Error(typeof detail === 'string' ? detail : 'Failed to send HR access');
    }
    return res.json();
  },

  /**
   * Technical-only report payload for client-side PDF export.
   * @param {string} candidateId
   */
  async getReportData(candidateId) {
    const { data: { session } } = await supabase.auth.getSession();
    const res = await fetch(
      `${API_BASE}/api/v1/candidates/${candidateId}/report-data`,
      { headers: { Authorization: `Bearer ${session?.access_token ?? ''}` } },
    );
    if (!res.ok) {
      let detail = 'Failed to load report data';
      try {
        const payload = await res.json();
        detail = payload?.detail || detail;
      } catch {
        /* ignore */
      }
      throw new Error(typeof detail === 'string' ? detail : 'Failed to load report data');
    }
    return res.json();
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
