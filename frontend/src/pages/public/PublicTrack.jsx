import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Package, RefreshCw, Users } from 'lucide-react';
import Badge from '../../components/ui/Badge';
import Button from '../../components/ui/Button';
import DataTable from '../../components/ui/DataTable';
import EmptyState from '../../components/ui/EmptyState';
import PageHeader from '../../components/ui/PageHeader';
import { SkeletonTable } from '../../components/ui/Skeleton';

const API_BASE = `${import.meta.env.VITE_API_URL || ''}/api/v1`;

function statusBadge(status) {
  if (status === 'completed') {
    return (
      <Badge variant="completed" showDot>
        Completed
      </Badge>
    );
  }
  if (status === 'in_progress') {
    return (
      <Badge variant="active" showDot>
        In Progress
      </Badge>
    );
  }
  return (
    <Badge variant="pending" showDot>
      Invited
    </Badge>
  );
}

export default function PublicTrack() {
  const { secret } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/track/${encodeURIComponent(secret)}`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || 'Tracker not found');
      }
      setData(await res.json());
    } catch (err) {
      setError(err.message || 'Failed to load tracker');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [secret]);

  useEffect(() => {
    load();
  }, [load]);

  const columns = useMemo(
    () => [
      {
        id: 'full_name',
        header: 'Candidate',
        accessor: (row) => row.full_name,
        cell: (row) => <span className="font-medium text-foreground">{row.full_name}</span>,
      },
      {
        id: 'status',
        header: 'Status',
        accessor: (row) => row.status,
        cell: (row) => statusBadge(row.status),
      },
      {
        id: 'progress',
        header: 'Progress',
        tabular: true,
        accessor: (row) => row.progress,
        cell: (row) => <span className="tabular-data text-foreground">{row.progress}</span>,
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
        cell: (row) => (
          <span className="tabular-data text-foreground">
            {row.jd_fit != null ? `${row.jd_fit}%` : '—'}
          </span>
        ),
      },
    ],
    [],
  );

  return (
    <div className="min-h-screen bg-canvas text-foreground">
      <header className="border-b border-border bg-surface">
        <div className="max-w-3xl mx-auto px-3 sm:px-4 h-12 flex items-center gap-2">
          <div className="w-7 h-7 rounded-md bg-primary/15 flex items-center justify-center border border-primary/25">
            <Package className="w-3.5 h-3.5 text-primary-text" />
          </div>
          <span className="text-sm font-semibold">MindQ</span>
          <span className="text-xs text-muted ml-auto">Public tracker</span>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-3 sm:px-4 py-6 space-y-4">
        {loading && (
          <div className="space-y-4" role="status" aria-label="Loading tracker">
            <SkeletonTable rows={5} cols={5} />
          </div>
        )}

        {!loading && error && (
          <div className="rounded-lg border border-danger/30 bg-danger/5 px-4 py-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div>
              <p className="text-sm font-medium text-foreground">Could not load tracker</p>
              <p className="text-xs text-muted mt-0.5">{error}</p>
            </div>
            <Button variant="secondary" size="sm" onClick={load}>
              <RefreshCw className="w-3.5 h-3.5" />
              Retry
            </Button>
          </div>
        )}

        {!loading && !error && data && (
          <>
            <PageHeader
              title={data.package_title}
              description={
                data.corporate_name
                  ? `${data.corporate_name} · Public completion board. Scores update as candidates finish.`
                  : 'Public completion board. Scores update as candidates finish.'
              }
            />

            <DataTable
              columns={columns}
              data={data.candidates || []}
              getRowId={(row) => `${row.full_name}-${row.progress}-${row.status}-${row.avg_score}`}
              empty={
                <EmptyState
                  icon={Users}
                  title="No candidates yet"
                  description="Candidates will appear here once they are invited to this assessment suite."
                />
              }
            />
          </>
        )}
      </main>
    </div>
  );
}
