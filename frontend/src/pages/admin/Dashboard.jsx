import React, { useCallback, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, Building2, Plus, Search, SearchX } from 'lucide-react';
import Button from '../../components/ui/Button';
import EmptyState from '../../components/ui/EmptyState';
import Input from '../../components/ui/Input';
import PageHeader from '../../components/ui/PageHeader';
import Skeleton from '../../components/ui/Skeleton';
import CorporateCard from './corporates/corporate-card';
import CorporateModal from './corporates/corporate-modal';
import { filterCorporates, useCorporates } from './corporates/use-corporates';

const GRID = 'grid grid-cols-1 lg:grid-cols-2 gap-4';

function CorporateGridSkeleton({ count = 6 }) {
  return (
    <div className={GRID} role="status" aria-label="Loading corporates">
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="h-24 flex items-center gap-4 px-4 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900"
        >
          <Skeleton className="h-16 w-16 rounded-md shrink-0" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-3 w-1/3" />
          </div>
          <div className="flex flex-col items-end gap-2">
            <Skeleton className="h-5 w-16 rounded-full" />
            <Skeleton className="h-3 w-24" />
          </div>
        </div>
      ))}
    </div>
  );
}

function CorporateFilterBar({ value, onChange, onSearch, onReset, canReset }) {
  const handleSubmit = (event) => {
    event.preventDefault();
    onSearch();
  };

  return (
    <form
      role="search"
      aria-label="Filter corporates"
      onSubmit={handleSubmit}
      className="flex flex-wrap items-center justify-end gap-2"
    >
      <div className="w-full sm:w-64">
        <Input
          icon={Search}
          type="search"
          placeholder="Keyword"
          aria-label="Keyword"
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      </div>
      <Button type="submit" variant="primary" size="md">
        Search
      </Button>
      <Button type="button" variant="secondary" size="md" onClick={onReset} disabled={!canReset}>
        Reset
      </Button>
    </form>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const { corporates, isLoading, error, reload, saveCorporate } = useCorporates();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [draftKeyword, setDraftKeyword] = useState('');
  const [appliedKeyword, setAppliedKeyword] = useState('');

  const visibleCorporates = useMemo(
    () => filterCorporates(corporates, appliedKeyword),
    [corporates, appliedKeyword],
  );

  const applySearch = useCallback(() => setAppliedKeyword(draftKeyword.trim()), [draftKeyword]);

  const resetSearch = useCallback(() => {
    setDraftKeyword('');
    setAppliedKeyword('');
  }, []);

  const openCreate = useCallback(() => {
    setEditing(null);
    setModalOpen(true);
  }, []);

  const openEdit = useCallback((corporate) => {
    setEditing(corporate);
    setModalOpen(true);
  }, []);

  const openCorporate = useCallback(
    (corporate) => navigate(`/admin/corporates/${corporate.id}`),
    [navigate],
  );

  const closeModal = useCallback(() => setModalOpen(false), []);

  let body;
  if (isLoading && corporates.length === 0) {
    body = <CorporateGridSkeleton />;
  } else if (error) {
    body = (
      <div
        role="alert"
        className="flex flex-col items-center gap-3 rounded-lg border border-danger/30 bg-danger/5 px-4 py-8 text-center"
      >
        <AlertTriangle className="w-5 h-5 text-danger" aria-hidden="true" />
        <div>
          <p className="text-sm font-semibold text-foreground">Could not load corporates</p>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{error}</p>
        </div>
        <Button variant="secondary" size="sm" onClick={reload}>
          Retry
        </Button>
      </div>
    );
  } else if (corporates.length === 0) {
    body = (
      <div className="rounded-lg border border-dashed border-slate-300 dark:border-slate-800">
        <EmptyState
          icon={Building2}
          title="No corporates yet"
          description="Create your first client to start building assessment suites for them."
          actionLabel="Create Corporate"
          onAction={openCreate}
        />
      </div>
    );
  } else if (visibleCorporates.length === 0) {
    body = (
      <div className="rounded-lg border border-dashed border-slate-300 dark:border-slate-800">
        <EmptyState
          icon={SearchX}
          title="No matching corporates"
          description={`Nothing matches "${appliedKeyword}". Try a different keyword.`}
          actionLabel="Reset filters"
          onAction={resetSearch}
        />
      </div>
    );
  } else {
    body = (
      <div className={GRID}>
        {visibleCorporates.map((corporate) => (
          <CorporateCard
            key={corporate.id}
            corporate={corporate}
            onOpen={openCorporate}
            onEdit={openEdit}
          />
        ))}
      </div>
    );
  }

  const countLabel = appliedKeyword
    ? `${visibleCorporates.length} of ${corporates.length} companies`
    : `${corporates.length} client ${corporates.length === 1 ? 'company' : 'companies'}`;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Manage Corporates"
        description={
          isLoading || error ? 'Client companies, HR contacts, and branding.' : countLabel
        }
        actions={
          <Button variant="accent" size="sm" onClick={openCreate}>
            <Plus className="w-3.5 h-3.5" aria-hidden="true" />
            Create Corporate
          </Button>
        }
      />

      <CorporateFilterBar
        value={draftKeyword}
        onChange={setDraftKeyword}
        onSearch={applySearch}
        onReset={resetSearch}
        canReset={Boolean(draftKeyword || appliedKeyword)}
      />

      {body}

      <CorporateModal
        isOpen={modalOpen}
        corporate={editing}
        onClose={closeModal}
        onSave={saveCorporate}
      />
    </div>
  );
}
