import React, { useCallback, useState } from 'react';
import { Package, RefreshCw, Search } from 'lucide-react';
import { SkeletonRows } from '../../components/ui/Skeleton';
import PackageAccordion from './package-accordion';
import { useClientDashboard } from './use-client-dashboard';
import { useClientSession } from './use-client-session';

function Metric({ label, value }) {
  return (
    <div className="px-4 py-3">
      <dt className="text-[11px] uppercase tracking-wider text-muted">{label}</dt>
      <dd className="mt-1 text-xl font-semibold tabular-nums text-foreground">{value}</dd>
    </div>
  );
}

export default function ClientDashboard() {
  const { corporate: sessionCorporate } = useClientSession();
  const { corporate, packages, totals, hasPackages, loading, error, search, setSearch, refetch } =
    useClientDashboard();
  const [expanded, setExpanded] = useState(() => new Set());
  const companyName = corporate?.name ?? sessionCorporate?.name ?? '';

  const forceOpen = Boolean(search.trim());

  const toggle = useCallback((id) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-foreground">Candidate Pipeline</h1>
          <p className="mt-1 text-sm text-muted">
            Read-only progress and MindQ Reports for your assessment suites.
          </p>
        </div>
        <label className="relative block sm:w-72">
          <span className="sr-only">Search suites or candidates</span>
          <Search
            aria-hidden="true"
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted"
          />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search suites or candidates"
            disabled={!hasPackages}
            className="h-9 w-full rounded-md border border-border bg-surface-raised pl-9 pr-3 text-sm text-foreground placeholder:text-muted focus:border-indigo-600 focus:outline-none focus:ring-1 focus:ring-indigo-600 disabled:opacity-50"
          />
        </label>
      </div>

      {!loading && hasPackages && (
        <dl className="grid grid-cols-3 divide-x divide-border rounded-lg border border-border bg-surface">
          <Metric label="Suites" value={totals.packages} />
          <Metric label="Invited" value={totals.invited} />
          <Metric label="Completed" value={totals.completed} />
        </dl>
      )}

      {error && (
        <div
          role="alert"
          className="flex items-center justify-between gap-3 rounded-md border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-700 dark:text-rose-300"
        >
          <span>{error}</span>
          <button
            type="button"
            onClick={refetch}
            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-rose-700 dark:text-rose-200 hover:bg-rose-500/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-400"
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            Retry
          </button>
        </div>
      )}

      {loading && <SkeletonRows rows={5} />}

      {!loading && !error && !hasPackages && (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border px-6 py-16 text-center">
          <Package className="h-6 w-6 text-muted" aria-hidden="true" />
          <p className="text-sm font-medium text-foreground">No active assessment suites</p>
          <p className="max-w-sm text-xs text-muted">
            Assessment suites appear here once your MindQ account manager publishes them.
          </p>
        </div>
      )}

      {!loading && hasPackages && packages.length === 0 && (
        <p className="rounded-lg border border-border px-4 py-8 text-center text-sm text-muted">
          No suites or candidates match “{search}”.
        </p>
      )}

      {!loading && packages.length > 0 && (
        <ul className="space-y-3">
          {packages.map((pkg) => (
            <PackageAccordion
              key={pkg.id}
              pkg={pkg}
              open={forceOpen || expanded.has(pkg.id)}
              onToggle={toggle}
              companyName={companyName}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
