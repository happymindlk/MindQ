import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Search, Download, Bell, Users, RefreshCw } from 'lucide-react';
import Button from '../../components/ui/Button';
import Input from '../../components/ui/Input';
import Badge from '../../components/ui/Badge';
import DataTable from '../../components/ui/DataTable';
import EmptyState from '../../components/ui/EmptyState';
import PageHeader from '../../components/ui/PageHeader';
import MetricStrip from '../../components/ui/MetricStrip';
import InviteCandidateForm from '../../components/InviteCandidateForm';
import { SkeletonTable } from '../../components/ui/Skeleton';
import { useToast } from '../../components/ui/useToast';
import { downloadMindQReport } from '../../features/mindq-report/render-report-pdf';
import {
  adminApi,
  candidateStatus,
  exportCandidatesCsv,
  maskEmail,
  maskAccessCode,
} from '../../lib/adminApi';

const STATUS_FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'invited', label: 'Invited' },
  { id: 'in_progress', label: 'In progress' },
  { id: 'completed', label: 'Completed' },
];

function statusBadge(status) {
  switch (status) {
    case 'completed':
      return (
        <Badge variant="completed" showDot>
          Completed
        </Badge>
      );
    case 'in_progress':
      return (
        <Badge variant="active" showDot>
          In Progress
        </Badge>
      );
    default:
      return <Badge variant="pending">Invited</Badge>;
  }
}

export default function CandidateTracker() {
  const { packageId } = useParams();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [candidates, setCandidates] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [nudgingId, setNudgingId] = useState(null);
  const [downloadingId, setDownloadingId] = useState(null);

  const loadCandidates = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      const data = await adminApi.getCandidates(packageId);
      setCandidates(data || []);
    } catch (err) {
      console.error('Failed to fetch candidates:', err);
      setLoadError(err.message || 'Failed to load candidates');
      setCandidates([]);
    } finally {
      setIsLoading(false);
    }
  }, [packageId]);

  useEffect(() => {
    loadCandidates();
  }, [loadCandidates]);

  const invited = candidates.length;
  const inProgress = candidates.filter((c) => candidateStatus(c) === 'in_progress').length;
  const completed = candidates.filter((c) => candidateStatus(c) === 'completed').length;

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return candidates.filter((c) => {
      const status = candidateStatus(c);
      if (statusFilter !== 'all' && status !== statusFilter) return false;
      if (!q) return true;
      return (
        (c.full_name || '').toLowerCase().includes(q) ||
        (c.email || '').toLowerCase().includes(q)
      );
    });
  }, [candidates, search, statusFilter]);

  const handleDownloadReport = useCallback(
    async (candidateId) => {
      setDownloadingId(candidateId);
      try {
        await downloadMindQReport(() => adminApi.getReportData(candidateId));
        toast({
          title: 'Report ready',
          description: 'MindQ Report PDF downloaded.',
          variant: 'success',
        });
        const data = await adminApi.getCandidates(packageId);
        setCandidates(data || []);
      } catch (err) {
        console.error('Failed to download report:', err);
        toast({
          title: 'Report download failed',
          description: err.message,
          variant: 'error',
        });
      } finally {
        setDownloadingId(null);
      }
    },
    [packageId, toast],
  );

  const handleNudge = useCallback(
    async (candidateId) => {
      setNudgingId(candidateId);
      try {
        await adminApi.nudgeCandidate(candidateId);
        toast({
          title: 'Reminder sent',
          description: 'Email reminder queued for the candidate.',
          variant: 'success',
        });
      } catch (err) {
        console.error('Failed to send reminder:', err);
        toast({ title: 'Reminder failed', description: err.message, variant: 'error' });
      } finally {
        setNudgingId(null);
      }
    },
    [toast],
  );

  const columns = useMemo(
    () => [
      {
        id: 'full_name',
        header: 'Candidate',
        accessor: (row) => row.full_name,
        cell: (row) => (
          <div>
            <div className="font-medium text-foreground text-sm">{row.full_name}</div>
            <div className="text-xs text-muted mt-0.5">{maskEmail(row.email)}</div>
            <div className="text-xs text-muted mt-0.5 tabular-data">{maskAccessCode(row.access_code)}</div>
          </div>
        ),
      },
      {
        id: 'package_title',
        header: 'Suite',
        accessor: (row) => row.package_title,
        cell: (row) => <span className="text-foreground/90">{row.package_title}</span>,
      },
      {
        id: 'status',
        header: 'Status',
        accessor: (row) => candidateStatus(row),
        cell: (row) => statusBadge(candidateStatus(row)),
      },
      {
        id: 'progress',
        header: 'Progress',
        tabular: true,
        accessor: (row) => Number(row.completed_assessments) || 0,
        cell: (row) => (
          <span className="tabular-data text-foreground">
            {row.completed_assessments}/{row.total_assessments}
          </span>
        ),
      },
      {
        id: 'avg_score',
        header: 'Score',
        tabular: true,
        accessor: (row) => (row.avg_score != null ? Number(row.avg_score) : -1),
        cell: (row) => (
          <span className="tabular-data text-foreground">
            {row.avg_score != null ? `${row.avg_score}%` : '—'}
          </span>
        ),
      },
      {
        id: 'jd_fit',
        header: 'JD fit',
        tabular: true,
        accessor: (row) => (row.jd_fit != null ? Number(row.jd_fit) : -1),
        cell: (row) => {
          if (row.jd_fit != null) {
            return <span className="tabular-data text-foreground">{row.jd_fit}%</span>;
          }
          if (candidateStatus(row) === 'completed') {
            return <Badge variant="scoring">Scoring</Badge>;
          }
          return <span className="text-neutral-400">—</span>;
        },
      },
      {
        id: 'actions',
        header: 'Actions',
        sortable: false,
        align: 'right',
        cell: (row) => {
          const status = candidateStatus(row);
          return (
            <div className="flex items-center justify-end gap-1" onClick={(e) => e.stopPropagation()}>
              {status === 'completed' ? (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleDownloadReport(row.id)}
                  isLoading={downloadingId === row.id}
                  title="Download MindQ Report"
                >
                  <Download className="w-3.5 h-3.5" />
                  Download Report
                </Button>
              ) : (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleNudge(row.id)}
                  isLoading={nudgingId === row.id}
                  title="Send reminder email"
                >
                  <Bell className="w-3.5 h-3.5" />
                  Send Reminder
                </Button>
              )}
            </div>
          );
        },
      },
    ],
    [downloadingId, nudgingId, handleDownloadReport, handleNudge],
  );

  return (
    <div className="space-y-4">
      <PageHeader
        title="HR Tracker"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {packageId && (
              <InviteCandidateForm
                packageId={packageId}
                compact
                onInvited={loadCandidates}
              />
            )}
            <Button
              variant="secondary"
              size="sm"
              onClick={() => exportCandidatesCsv(filtered)}
              disabled={filtered.length === 0}
            >
              <Download className="w-3.5 h-3.5" />
              Export CSV
            </Button>
          </div>
        }
      />

      <MetricStrip
        items={[
          { label: 'Invited', value: invited, hint: 'Registered' },
          { label: 'In progress', value: inProgress, tone: 'warning', hint: 'Active' },
          { label: 'Completed', value: completed, tone: 'success', hint: 'Finished' },
        ]}
      />

      <div className="rounded-lg border border-slate-200 dark:border-neutral-800 bg-surface">
        <div className="flex flex-col gap-3 p-3 border-b border-slate-200 dark:border-neutral-800 sm:flex-row sm:items-center sm:justify-between">
          <Input
            icon={Search}
            placeholder="Search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="max-w-sm"
            aria-label="Search candidates"
          />
          <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Status filter">
            {STATUS_FILTERS.map((f) => (
              <button
                key={f.id}
                type="button"
                aria-pressed={statusFilter === f.id}
                onClick={() => setStatusFilter(f.id)}
                className={`
                  px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors duration-150
                  focus-visible:ring-2 focus-visible:ring-primary
                  ${
                    statusFilter === f.id
                      ? 'bg-primary/15 text-primary-text'
                      : 'text-muted hover:text-foreground hover:bg-surface-raised'
                  }
                `}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        <div className="p-0">
          {isLoading && (
            <div className="p-3">
              <SkeletonTable rows={8} cols={7} />
            </div>
          )}

          {!isLoading && loadError && (
            <div className="m-3 rounded-lg border border-danger/30 bg-danger/5 px-3 py-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
              <div>
                <p className="text-sm font-medium text-foreground">Could not load tracker</p>
                <p className="text-xs text-muted mt-0.5">{loadError}</p>
              </div>
              <Button variant="secondary" size="sm" onClick={loadCandidates}>
                <RefreshCw className="w-3.5 h-3.5" />
                Retry
              </Button>
            </div>
          )}

          {!isLoading && !loadError && candidates.length === 0 && (
            <EmptyState icon={Users} title="No candidates" />
          )}

          {!isLoading && !loadError && candidates.length > 0 && (
            <DataTable
              columns={columns}
              data={filtered}
              getRowId={(row) => row.id}
              onRowClick={(row) => navigate(`/admin/candidates/${row.id}`)}
              empty={
                <EmptyState
                  icon={Search}
                  title="No matches"
                  actionLabel="Clear filters"
                  onAction={() => {
                    setSearch('');
                    setStatusFilter('all');
                  }}
                />
              }
              className="border-0 rounded-none"
            />
          )}
        </div>
      </div>
    </div>
  );
}
