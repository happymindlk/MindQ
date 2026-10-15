import { useCallback, useMemo, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { useBuilderToast } from '../hooks/use-builder-toast';
import type { ModuleLibraryState } from '../hooks/use-module-library';
import type { AssessmentModule, ModuleCreateInput } from '../types/module';
import { ArchiveDialog } from './archive-dialog';
import { CreateModuleDialog } from './create-module-dialog';
import type { CreateModuleDraft } from './create-module-dialog';
import { ModuleEditorDrawer } from './module-editor-drawer';
import { ModuleLibraryHub } from './module-library-hub';
import type { HubFilter } from './module-library-hub';
import { NeonButton } from './primitives';

interface AssessmentBuilderWorkspaceProps {
  library: ModuleLibraryState;
  filter: HubFilter;
  search: string;
  createDraft: CreateModuleDraft | null;
  onCreateDraftChange: (draft: CreateModuleDraft | null) => void;
}

/**
 * Library hub + module editor drawer + lifecycle dialogs. The host page owns
 * the header, search, and tabs, and passes the shared library state in.
 */
export function AssessmentBuilderWorkspace({
  library,
  filter,
  search,
  createDraft,
  onCreateDraftChange,
}: AssessmentBuilderWorkspaceProps) {
  const { toast } = useBuilderToast();
  const { modules, loading, error, refresh, createModule, archiveModule, upsertLocal } = library;
  const [openId, setOpenId] = useState<string | null>(null);
  const [archiveId, setArchiveId] = useState<string | null>(null);
  const [archiving, setArchiving] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createKey, setCreateKey] = useState(0);

  const archiveTarget = useMemo<AssessmentModule | null>(
    () => modules.find((m) => m.id === archiveId) ?? null,
    [archiveId, modules],
  );

  const onCreate = useCallback(
    async (input: ModuleCreateInput) => {
      setCreating(true);
      try {
        const created = await createModule(input);
        onCreateDraftChange(null);
        toast({ title: `Draft v${created.version} created`, variant: 'success' });
        setOpenId(created.id);
      } catch (err) {
        toast({ title: err instanceof Error ? err.message : 'Could not create this module.', variant: 'error' });
      } finally {
        setCreating(false);
      }
    },
    [createModule, onCreateDraftChange, toast],
  );

  const onArchive = useCallback(async () => {
    if (!archiveTarget) return;
    setArchiving(true);
    try {
      await archiveModule(archiveTarget.id);
      toast({
        title: `Archived “${archiveTarget.title}” v${archiveTarget.version}`,
        description: 'Historical responses remain intact.',
        variant: 'success',
      });
      if (openId === archiveTarget.id) setOpenId(null);
      setArchiveId(null);
    } catch (err) {
      toast({ title: err instanceof Error ? err.message : 'Could not archive this module.', variant: 'error' });
    } finally {
      setArchiving(false);
    }
  }, [archiveModule, archiveTarget, openId, toast]);

  const requestCreate = useCallback(
    (kind: CreateModuleDraft['kind'], category: CreateModuleDraft['category']) => {
      setCreateKey((k) => k + 1);
      onCreateDraftChange({ kind, category });
    },
    [onCreateDraftChange],
  );

  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-slate-900 sm:p-6 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-100">
      {error && (
        <div role="alert" className="mb-4 flex items-center justify-between gap-2 rounded-lg border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-500/40 dark:bg-rose-500/10 dark:text-rose-200">
          <span className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4" aria-hidden /> {error}
          </span>
          <NeonButton size="sm" variant="outline" onClick={() => void refresh()}>
            Retry
          </NeonButton>
        </div>
      )}

      <ModuleLibraryHub
        modules={modules}
        filter={filter}
        search={search}
        activeId={openId}
        loading={loading}
        onOpen={setOpenId}
        onArchive={setArchiveId}
        onCreate={requestCreate}
      />

      <ModuleEditorDrawer
        moduleId={openId}
        onClose={() => setOpenId(null)}
        onModuleChanged={upsertLocal}
        onOpenModule={setOpenId}
        onRequestArchive={setArchiveId}
      />

      <ArchiveDialog
        key={archiveId ?? 'none'}
        module={archiveTarget}
        open={archiveTarget !== null}
        onOpenChange={(open) => !open && !archiving && setArchiveId(null)}
        onConfirm={() => void onArchive()}
        archiving={archiving}
      />

      <CreateModuleDialog
        key={createDraft ? `${createKey}-${createDraft.kind}-${createDraft.category ?? ''}` : 'closed'}
        draft={createDraft}
        onOpenChange={(open) => !open && !creating && onCreateDraftChange(null)}
        onCreate={onCreate}
        creating={creating}
      />
    </div>
  );
}
