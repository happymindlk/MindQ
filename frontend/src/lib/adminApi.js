import { supabase } from './supabaseClient';

const API_BASE = import.meta.env.VITE_API_URL || '';

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

  // Report generation stays in the FastAPI service (WeasyPrint + service_role).
  // We authenticate the request with the HR user's Supabase access token.
  async downloadReport(candidateId) {
    const { data: { session } } = await supabase.auth.getSession();
    const res = await fetch(`${API_BASE}/api/v1/admin/candidates/${candidateId}/report`, {
      headers: { Authorization: `Bearer ${session?.access_token ?? ''}` },
    });
    if (!res.ok) throw new Error('Failed to download report');
    const blob = await res.blob();
    const isHtml = (res.headers.get('content-type') || '').includes('text/html');
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `report-${candidateId}.${isHtml ? 'html' : 'pdf'}`;
    a.click();
    window.URL.revokeObjectURL(url);
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
