import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Building2,
  CalendarClock,
  ChevronDown,
  Download,
  Package,
  Pencil,
  Search,
  Users,
} from 'lucide-react';
import Input from '../../components/ui/Input';
import EmptyState from '../../components/ui/EmptyState';
import PageHeader from '../../components/ui/PageHeader';
import InviteCandidateForm from '../../components/InviteCandidateForm';
import Badge from '../../components/ui/Badge';
import Button from '../../components/ui/Button';
import { SkeletonRows } from '../../components/ui/Skeleton';
import { adminApi, maskEmail } from '../../lib/adminApi';
import { downloadMindQReport } from '../../features/mindq-report/render-report-pdf';
import { formatDate } from '../../lib/format-date';
import DeadlineLabel from '../../features/package-schedule/deadline-label';
import ExtendDeadlineModal from '../../features/package-schedule/extend-deadline-modal';
import {
  PIPELINE_BADGE_VARIANT,
  PIPELINE_LABEL,
  packageLifecycleStatus,
  pipelineStatus,
} from '../../lib/pipeline-status';

function AccordionPanel({ open, children }) {
  return (
    <div
      className={`grid transition-[grid-template-rows] duration-300 ease-out ${
        open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
      }`}
    >
      <div className="overflow-hidden min-h-0">{children}</div>
    </div>
  );
}

function StatusBadge({ status }) {
  const variant = PIPELINE_BADGE_VARIANT[status] || 'pending';
  return (
    <Badge variant={variant} showDot={status === 'completed'}>
      {PIPELINE_LABEL[status] || status}
    </Badge>
  );
}

function HrInviteInline({ companyId, invitedEmail, onInvited }) {
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async (event) => {
    event.preventDefault();
    event.stopPropagation();
    const trimmed = email.trim();
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    try {
      const result = await adminApi.inviteHr(companyId, trimmed);
      onInvited?.(result.email || trimmed);
      setEmail('');
    } catch (err) {
      setError(err.message || 'Invite failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="flex flex-col items-end gap-1 shrink-0"
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
      {invitedEmail ? (
        <Badge variant="success" className="text-[10px]">
          HR Access: {invitedEmail}
        </Badge>
      ) : null}
      <form onSubmit={submit} className="flex items-center gap-1.5">
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="hr@company.com"
          aria-label="HR invite email"
          className="h-8 w-40 sm:w-48 rounded-md bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-900 dark:text-slate-100 placeholder:text-slate-400 text-xs px-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
        />
        <Button type="submit" size="sm" variant="secondary" disabled={busy} isLoading={busy}>
          Send Access
        </Button>
      </form>
      {error && <p className="text-[10px] text-rose-600 dark:text-rose-400 max-w-[220px] text-right">{error}</p>}
    </div>
  );
}

export default function AssessmentHistory() {
  const { companyId, packageId } = useParams();
  const navigate = useNavigate();
  const [companies, setCompanies] = useState([]);
  const [packagesByCompany, setPackagesByCompany] = useState({});
  const [candidatesByPackage, setCandidatesByPackage] = useState({});
  const [expandedCompanies, setExpandedCompanies] = useState(() => new Set());
  const [expandedPackages, setExpandedPackages] = useState(() => new Set());
  const [loadingCompanies, setLoadingCompanies] = useState(true);
  const [loadingPackages, setLoadingPackages] = useState({});
  const [loadingCandidates, setLoadingCandidates] = useState({});
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');
  const [hrEmails, setHrEmails] = useState({});
  const [downloadingId, setDownloadingId] = useState(null);
  const [deadlineTarget, setDeadlineTarget] = useState(null);

  const onDeadlineSaved = useCallback((updated) => {
    setPackagesByCompany((prev) => {
      const next = {};
      Object.entries(prev).forEach(([corp, pkgs]) => {
        next[corp] = pkgs.map((p) =>
          p.id === updated.id
            ? { ...p, open_time: updated.open_time, close_time: updated.close_time }
            : p,
        );
      });
      return next;
    });
    setDeadlineTarget(null);
  }, []);

  const loadCompanies = useCallback(async () => {
    setLoadingCompanies(true);
    setError(null);
    try {
      const rows = await adminApi.listCorporates();
      setCompanies(rows || []);
      const seeded = {};
      (rows || []).forEach((c) => {
        if (c.contact_email) seeded[c.id] = c.contact_email;
      });
      setHrEmails((prev) => ({ ...seeded, ...prev }));
    } catch (err) {
      setError(err.message || 'Failed to load history');
    } finally {
      setLoadingCompanies(false);
    }
  }, []);

  const loadPackages = useCallback(async (corpId) => {
    setLoadingPackages((prev) => ({ ...prev, [corpId]: true }));
    try {
      const pkgRows = await adminApi.getPackages();
      const scoped = (pkgRows || []).filter((p) => p.corporate_id === corpId);
      setPackagesByCompany((prev) => ({ ...prev, [corpId]: scoped }));
    } catch (err) {
      setError(err.message || 'Failed to load assessment suites');
    } finally {
      setLoadingPackages((prev) => ({ ...prev, [corpId]: false }));
    }
  }, []);

  const loadCandidates = useCallback(async (pkgId) => {
    setLoadingCandidates((prev) => ({ ...prev, [pkgId]: true }));
    try {
      const cand = await adminApi.getCandidates(pkgId);
      setCandidatesByPackage((prev) => ({ ...prev, [pkgId]: cand || [] }));
    } catch (err) {
      setError(err.message || 'Failed to load candidates');
    } finally {
      setLoadingCandidates((prev) => ({ ...prev, [pkgId]: false }));
    }
  }, []);

  useEffect(() => {
    loadCompanies();
  }, [loadCompanies]);

  useEffect(() => {
    if (!companyId) return;
    setExpandedCompanies((prev) => new Set(prev).add(companyId));
    if (!packagesByCompany[companyId] && !loadingPackages[companyId]) {
      loadPackages(companyId);
    }
  }, [companyId, packagesByCompany, loadingPackages, loadPackages]);

  useEffect(() => {
    if (!packageId || !companyId) return;
    setExpandedPackages((prev) => new Set(prev).add(packageId));
    if (!candidatesByPackage[packageId] && !loadingCandidates[packageId]) {
      loadCandidates(packageId);
    }
  }, [packageId, companyId, candidatesByPackage, loadingCandidates, loadCandidates]);

  const q = search.trim().toLowerCase();

  const filteredCompanies = useMemo(() => {
    if (!q) return companies;
    return companies.filter(
      (c) => c.name.toLowerCase().includes(q) || (c.slug || '').includes(q),
    );
  }, [companies, q]);

  const toggleCompany = (corpId) => {
    setExpandedCompanies((prev) => {
      const next = new Set(prev);
      if (next.has(corpId)) {
        next.delete(corpId);
        navigate('/admin/history');
      } else {
        next.add(corpId);
        navigate(`/admin/history/${corpId}`);
        if (!packagesByCompany[corpId]) loadPackages(corpId);
      }
      return next;
    });
  };

  const togglePackage = (corpId, pkgId) => {
    setExpandedPackages((prev) => {
      const next = new Set(prev);
      if (next.has(pkgId)) {
        next.delete(pkgId);
        navigate(`/admin/history/${corpId}`);
      } else {
        next.add(pkgId);
        navigate(`/admin/history/${corpId}/${pkgId}`);
        if (!candidatesByPackage[pkgId]) loadCandidates(pkgId);
      }
      return next;
    });
  };

  const onDownloadReport = async (candidateId) => {
    setDownloadingId(candidateId);
    setError(null);
    try {
      await downloadMindQReport(() => adminApi.getReportData(candidateId));
    } catch (err) {
      setError(err.message || 'Failed to download report');
    } finally {
      setDownloadingId(null);
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Assessment History"
        actions={
          <Input
            icon={Search}
            placeholder="Search companies"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-40 sm:w-56"
            aria-label="Search history"
          />
        }
      />

      {error && (
        <div className="rounded-lg border border-rose-500/30 px-3 py-2 text-sm text-rose-600 dark:text-rose-400">
          {error}
        </div>
      )}

      {loadingCompanies && <SkeletonRows rows={6} />}

      {!loadingCompanies && filteredCompanies.length === 0 && (
        <EmptyState icon={Building2} title="No companies" />
      )}

      {!loadingCompanies && filteredCompanies.length > 0 && (
        <ul className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 divide-y divide-slate-200 dark:divide-slate-800 overflow-hidden">
          {filteredCompanies.map((corp) => {
            const corpOpen = expandedCompanies.has(corp.id);
            const pkgs = packagesByCompany[corp.id] || [];
            const filteredPkgs = q
              ? pkgs.filter((p) => p.title.toLowerCase().includes(q))
              : pkgs;
            const hrEmail = hrEmails[corp.id] || corp.contact_email || null;

            return (
              <li key={corp.id}>
                <div className="flex items-center gap-3 px-4 py-3 hover:bg-slate-50 dark:hover:bg-slate-800/60 transition-colors">
                  <button
                    type="button"
                    onClick={() => toggleCompany(corp.id)}
                    className="flex-1 flex items-center gap-3 text-left min-w-0"
                    aria-expanded={corpOpen}
                  >
                    <ChevronDown
                      className={`w-4 h-4 text-slate-500 dark:text-slate-400 shrink-0 transition-transform duration-200 ${
                        corpOpen ? 'rotate-0' : '-rotate-90'
                      }`}
                    />
                    <Building2 className="w-4 h-4 text-slate-500 dark:text-slate-400 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-slate-900 dark:text-slate-100 truncate">
                        {corp.name}
                      </p>
                      <p className="text-[11px] font-mono text-slate-500 dark:text-slate-400 mt-0.5">
                        {corp.slug}
                      </p>
                    </div>
                    <span className="text-xs text-slate-500 dark:text-slate-400 tabular-nums shrink-0 hidden sm:inline">
                      {corp.package_count ?? 0} active pkgs
                    </span>
                  </button>
                  <HrInviteInline
                    companyId={corp.id}
                    invitedEmail={hrEmail}
                    onInvited={(email) =>
                      setHrEmails((prev) => ({ ...prev, [corp.id]: email }))
                    }
                  />
                </div>

                <AccordionPanel open={corpOpen}>
                  <div className="bg-slate-50 dark:bg-slate-950/60 border-t border-slate-200 dark:border-slate-800">
                    {loadingPackages[corp.id] && (
                      <div className="px-4 py-3">
                        <SkeletonRows rows={3} />
                      </div>
                    )}
                    {!loadingPackages[corp.id] && filteredPkgs.length === 0 && (
                      <EmptyState
                        icon={Package}
                        title="No assessment suites"
                        className="py-8"
                        actionLabel="Suite Builder"
                        onAction={() => navigate('/admin/packages/create')}
                      />
                    )}
                    {filteredPkgs.map((pkg) => {
                      const pkgOpen = expandedPackages.has(pkg.id);
                      const lifecycle = packageLifecycleStatus(pkg.status, pkg.is_active);
                      const cands = candidatesByPackage[pkg.id] || [];
                      const filteredCands = q
                        ? cands.filter(
                            (c) =>
                              (c.full_name || '').toLowerCase().includes(q) ||
                              (c.email || '').toLowerCase().includes(q),
                          )
                        : cands;
                      const isDraft = lifecycle === 'draft';

                      return (
                        <div key={pkg.id} className="border-b border-slate-200 dark:border-slate-800 last:border-b-0">
                          <div className="flex items-center gap-2 pl-8 pr-4 py-2.5 hover:bg-slate-100/70 dark:hover:bg-slate-900/80 transition-colors">
                            <button
                              type="button"
                              onClick={() => togglePackage(corp.id, pkg.id)}
                              className="flex-1 flex items-center gap-3 text-left min-w-0"
                              aria-expanded={pkgOpen}
                            >
                              <ChevronDown
                                className={`w-3.5 h-3.5 text-slate-500 dark:text-slate-400 shrink-0 transition-transform duration-200 ${
                                  pkgOpen ? 'rotate-0' : '-rotate-90'
                                }`}
                              />
                              <Package className="w-3.5 h-3.5 text-slate-500 dark:text-slate-400 shrink-0" />
                              <div className="flex-1 min-w-0">
                                <p className="text-sm text-slate-900 dark:text-slate-100 truncate">
                                  {pkg.title}
                                </p>
                                {pkg.target_role && (
                                  <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5 truncate">
                                    {pkg.target_role}
                                  </p>
                                )}
                                <DeadlineLabel closeTime={pkg.close_time} className="mt-0.5" />
                              </div>
                              <StatusBadge status={lifecycle} />
                              <span className="text-xs text-slate-500 dark:text-slate-400 tabular-nums w-16 text-right shrink-0">
                                {pkg.candidate_count ?? 0} cand.
                              </span>
                            </button>
                            {isDraft && (
                              <button
                                type="button"
                                aria-label="Edit Draft"
                                title="Edit Draft"
                                onClick={() => navigate(`/admin/packages/edit/${pkg.id}`)}
                                className="p-1.5 rounded text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800"
                              >
                                <Pencil className="w-3.5 h-3.5" />
                              </button>
                            )}
                            {lifecycle === 'locked' && (
                              <button
                                type="button"
                                aria-label={`Extend deadline for ${pkg.title}`}
                                title="Extend deadline"
                                onClick={() => setDeadlineTarget(pkg)}
                                className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-md text-xs font-medium text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-slate-800 hover:text-slate-900 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                              >
                                <CalendarClock className="w-3.5 h-3.5" aria-hidden="true" />
                                Extend deadline
                              </button>
                            )}
                          </div>

                          <AccordionPanel open={pkgOpen}>
                            <div className="pl-14 pr-4 pb-3 bg-slate-50 dark:bg-slate-950/60">
                              <div className="flex justify-end mb-2">
                                <InviteCandidateForm
                                  packageId={pkg.id}
                                  corporateId={corp.id}
                                  compact
                                  onInvited={() => loadCandidates(pkg.id)}
                                />
                              </div>
                              {loadingCandidates[pkg.id] && <SkeletonRows rows={3} />}
                              {!loadingCandidates[pkg.id] && filteredCands.length === 0 && (
                                <EmptyState
                                  icon={Users}
                                  title="No candidates"
                                  className="py-6"
                                />
                              )}
                              {!loadingCandidates[pkg.id] && filteredCands.length > 0 && (
                                <ul className="rounded-md border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 divide-y divide-slate-200 dark:divide-slate-800 overflow-hidden">
                                  <li className="grid grid-cols-[1.4fr_0.8fr_0.5fr_0.5fr_0.7fr_0.4fr] gap-2 px-3 py-1.5 text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-950/60">
                                    <span>Name / Email</span>
                                    <span>Progress</span>
                                    <span>Score</span>
                                    <span>Status</span>
                                    <span>Completed</span>
                                    <span className="text-right">Report</span>
                                  </li>
                                  {filteredCands.map((cand) => {
                                    const status = pipelineStatus(cand);
                                    const score =
                                      cand.technical_score ?? cand.avg_score;
                                    const completed = status === 'completed';
                                    return (
                                      <li key={cand.id}>
                                        <div className="grid grid-cols-[1.4fr_0.8fr_0.5fr_0.5fr_0.7fr_0.4fr] gap-2 px-3 py-2 hover:bg-slate-100/70 dark:hover:bg-slate-900/80 transition-colors">
                                          <button
                                            type="button"
                                            onClick={() =>
                                              navigate(`/admin/candidates/${cand.id}`)
                                            }
                                            className="min-w-0 text-left"
                                          >
                                            <span className="block text-sm text-slate-900 dark:text-slate-100 truncate">
                                              {cand.full_name}
                                            </span>
                                            <span className="block text-xs text-slate-500 dark:text-slate-400 truncate">
                                              {maskEmail(cand.email)}
                                            </span>
                                          </button>
                                          <span className="text-xs text-slate-500 dark:text-slate-400 tabular-nums self-center">
                                            {cand.completed_assessments}/
                                            {cand.total_assessments}
                                          </span>
                                          <span className="text-xs text-slate-900 dark:text-slate-100 tabular-nums self-center">
                                            {score != null ? `${score}%` : '—'}
                                          </span>
                                          <span className="self-center">
                                            <StatusBadge status={status} />
                                          </span>
                                          <span className="text-xs text-slate-500 dark:text-slate-400 self-center">
                                            {formatDate(cand.completed_at)}
                                          </span>
                                          <span className="self-center flex justify-end">
                                            {completed && (
                                              <button
                                                type="button"
                                                title="Download Report"
                                                aria-label="Download Report"
                                                disabled={downloadingId === cand.id}
                                                onClick={() => onDownloadReport(cand.id)}
                                                className="p-1.5 rounded text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40"
                                              >
                                                <Download className="w-3.5 h-3.5" />
                                              </button>
                                            )}
                                          </span>
                                        </div>
                                      </li>
                                    );
                                  })}
                                </ul>
                              )}
                            </div>
                          </AccordionPanel>
                        </div>
                      );
                    })}
                  </div>
                </AccordionPanel>
              </li>
            );
          })}
        </ul>
      )}

      <ExtendDeadlineModal
        isOpen={deadlineTarget !== null}
        onClose={() => setDeadlineTarget(null)}
        pkg={deadlineTarget}
        onSaved={onDeadlineSaved}
      />
    </div>
  );
}
