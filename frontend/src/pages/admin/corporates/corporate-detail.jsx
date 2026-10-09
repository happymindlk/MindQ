import React, { useCallback, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, ArrowLeft, Building2, Package } from 'lucide-react';
import Button from '../../../components/ui/Button';
import EmptyState from '../../../components/ui/EmptyState';
import Skeleton from '../../../components/ui/Skeleton';
import CorporateLogo from './corporate-logo';
import CorporatePackageCard from './corporate-package-card';
import SharePackageModal from './share-package-modal';
import ExtendDeadlineModal from '../../../features/package-schedule/extend-deadline-modal';
import { useCorporates } from './use-corporates';
import { useCorporatePackages } from './use-corporate-packages';

const GRID = 'grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4';

function PackageGridSkeleton({ count = 3 }) {
  return (
    <div className={GRID} role="status" aria-label="Loading assessment suites">
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="rounded-lg border border-slate-200 dark:border-neutral-800 bg-white dark:bg-neutral-950 p-4 space-y-4"
        >
          <div className="flex justify-between gap-3">
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="h-3 w-1/3" />
            </div>
            <Skeleton className="h-5 w-20 rounded-full" />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
          </div>
          <Skeleton className="h-8 w-36" />
        </div>
      ))}
    </div>
  );
}

function ErrorPanel({ title, message, onRetry }) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center gap-3 rounded-lg border border-danger/30 bg-danger/5 px-4 py-8 text-center"
    >
      <AlertTriangle className="w-5 h-5 text-danger" aria-hidden="true" />
      <div>
        <p className="text-sm font-semibold text-foreground">{title}</p>
        <p className="mt-1 text-xs text-neutral-400">{message}</p>
      </div>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}

/**
 * Ops corporate history: profile header plus the corporate's assessment packages.
 */
export default function CorporateDetail() {
  const { corporateId } = useParams();
  const navigate = useNavigate();
  const {
    corporates,
    isLoading: corporatesLoading,
    error: corporatesError,
    reload: reloadCorporates,
  } = useCorporates();
  const {
    packages,
    isLoading: packagesLoading,
    error: packagesError,
    reload: reloadPackages,
    patchPackage,
  } = useCorporatePackages(corporateId);
  const [sharePkg, setSharePkg] = useState(null);
  const [shareOpen, setShareOpen] = useState(false);
  const [deadlinePkg, setDeadlinePkg] = useState(null);

  const onDeadlineSaved = useCallback(
    (updated) => {
      patchPackage(updated.id, { open_time: updated.open_time, close_time: updated.close_time });
      setDeadlinePkg(null);
    },
    [patchPackage],
  );
  const closeDeadline = useCallback(() => setDeadlinePkg(null), []);

  const corporate = useMemo(
    () => corporates.find((c) => c.id === corporateId) ?? null,
    [corporates, corporateId],
  );

  const openShare = useCallback((pkg) => {
    setSharePkg(pkg);
    setShareOpen(true);
  }, []);
  const closeShare = useCallback(() => setShareOpen(false), []);

  const backButton = (
    <Button variant="secondary" size="sm" onClick={() => navigate('/admin')}>
      <ArrowLeft className="w-3.5 h-3.5" aria-hidden="true" />
      Back to Dashboard
    </Button>
  );

  if (corporatesLoading) {
    return (
      <div className="space-y-6">
        {backButton}
        <div className="flex items-center gap-4" role="status" aria-label="Loading corporate">
          <Skeleton className="h-16 w-16 rounded-md" />
          <div className="space-y-2">
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-3 w-32" />
          </div>
        </div>
        <PackageGridSkeleton />
      </div>
    );
  }

  if (corporatesError) {
    return (
      <div className="space-y-6">
        {backButton}
        <ErrorPanel
          title="Could not load corporate"
          message={corporatesError}
          onRetry={reloadCorporates}
        />
      </div>
    );
  }

  if (!corporate) {
    return (
      <div className="space-y-6">
        {backButton}
        <EmptyState
          icon={Building2}
          title="Corporate not found"
          description="It may have been removed, or the link is incorrect."
        />
      </div>
    );
  }

  let packagesBody;
  if (packagesLoading && packages.length === 0) {
    packagesBody = <PackageGridSkeleton />;
  } else if (packagesError) {
    packagesBody = (
      <ErrorPanel title="Could not load assessment suites" message={packagesError} onRetry={reloadPackages} />
    );
  } else if (packages.length === 0) {
    packagesBody = (
      <div className="rounded-lg border border-dashed border-slate-300 dark:border-neutral-800">
        <EmptyState
          icon={Package}
          title="No assessment suites yet"
          description={`Build the first assessment suite for ${corporate.name}.`}
          actionLabel="Open Suite Builder"
          onAction={() => navigate('/admin/packages/create')}
        />
      </div>
    );
  } else {
    packagesBody = (
      <div className={GRID}>
        {packages.map((pkg) => (
          <CorporatePackageCard
            key={pkg.id}
            pkg={pkg}
            corporateId={corporate.id}
            onShare={openShare}
            onExtendDeadline={setDeadlinePkg}
          />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {backButton}

      <header className="flex items-center gap-4">
        <CorporateLogo name={corporate.name} logoUrl={corporate.logo_url} size="lg" />
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight text-foreground truncate">
            {corporate.name}
          </h1>
          <p className="mt-1 text-xs text-neutral-400 truncate">
            {corporate.contact_email || 'No HR email'}
          </p>
        </div>
      </header>

      <section aria-labelledby="packages-heading" className="space-y-3">
        <div className="flex items-baseline justify-between gap-2">
          <h2 id="packages-heading" className="metric-label">
            Published Suites
          </h2>
          {!packagesLoading && !packagesError && (
            <span className="text-xs tabular-data text-neutral-400">{packages.length} total</span>
          )}
        </div>
        {packagesBody}
      </section>

      <SharePackageModal
        isOpen={shareOpen}
        pkg={sharePkg}
        corporate={corporate}
        onClose={closeShare}
      />

      <ExtendDeadlineModal
        isOpen={deadlinePkg !== null}
        onClose={closeDeadline}
        pkg={deadlinePkg}
        onSaved={onDeadlineSaved}
      />
    </div>
  );
}
