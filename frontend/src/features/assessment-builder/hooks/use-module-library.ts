import { useCallback } from 'react';
import { libraryApi } from '../api/library-api';
import type { AssessmentModule, AssessmentModuleDetail, ModuleCreateInput } from '../types/module';
import { useCachedQuery } from '../../../hooks/use-cached-query';

export const LIBRARY_MODULES_QUERY_KEY = 'admin:library-modules';

export interface ModuleLibraryState {
  modules: AssessmentModule[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  createModule: (input: ModuleCreateInput) => Promise<AssessmentModuleDetail>;
  archiveModule: (id: string) => Promise<void>;
  upsertLocal: (module: AssessmentModule) => void;
}

/**
 * Library list state. Mutations update the local list optimistically from the
 * server response so the hub never needs a full refetch after an edit.
 *
 * @returns Modules plus create/archive/refresh actions.
 */
export function useModuleLibrary(): ModuleLibraryState {
  const fetcher = useCallback(() => libraryApi.listModules(), []);
  const { data, error, isLoading, reload, mutate } = useCachedQuery<AssessmentModule[]>(
    LIBRARY_MODULES_QUERY_KEY,
    fetcher,
  );

  const upsertLocal = useCallback(
    (module: AssessmentModule) => {
      mutate((prev) => {
        const rows = Array.isArray(prev) ? prev : [];
        const index = rows.findIndex((m) => m.id === module.id);
        if (!module.isActive) return rows.filter((m) => m.id !== module.id);
        if (index === -1) return [...rows, module];
        return rows.map((m) => (m.id === module.id ? module : m));
      });
    },
    [mutate],
  );

  const createModule = useCallback(
    async (input: ModuleCreateInput) => {
      const created = await libraryApi.createModule(input);
      upsertLocal(created);
      return created;
    },
    [upsertLocal],
  );

  const archiveModule = useCallback(
    async (id: string) => {
      await libraryApi.archiveModule(id);
      mutate((prev) => (Array.isArray(prev) ? prev.filter((m) => m.id !== id) : []));
    },
    [mutate],
  );

  return {
    modules: Array.isArray(data) ? data : [],
    loading: isLoading,
    error: error || null,
    refresh: reload,
    createModule,
    archiveModule,
    upsertLocal,
  };
}
