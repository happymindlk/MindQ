import { useCallback, useEffect, useRef, useState } from 'react';
import { libraryApi } from '../api/library-api';
import type { AssessmentModule, AssessmentModuleDetail, ModuleCreateInput } from '../types/module';

export interface ModuleLibraryState {
  modules: AssessmentModule[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  createModule: (input: ModuleCreateInput) => Promise<AssessmentModuleDetail>;
  archiveModule: (id: string) => Promise<void>;
  upsertLocal: (module: AssessmentModule) => void;
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

/**
 * Library list state. Mutations update the local list optimistically from the
 * server response so the hub never needs a full refetch after an edit.
 *
 * @returns Modules plus create/archive/refresh actions.
 */
export function useModuleLibrary(): ModuleLibraryState {
  const [modules, setModules] = useState<AssessmentModule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestRef = useRef(0);

  const refresh = useCallback(async () => {
    const requestId = ++requestRef.current;
    setLoading(true);
    setError(null);
    try {
      const rows = await libraryApi.listModules();
      if (requestId === requestRef.current) setModules(rows);
    } catch (err) {
      if (requestId === requestRef.current) setError(errorMessage(err, 'Could not load the assessment library.'));
    } finally {
      if (requestId === requestRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const upsertLocal = useCallback((module: AssessmentModule) => {
    setModules((prev) => {
      const index = prev.findIndex((m) => m.id === module.id);
      if (!module.isActive) return prev.filter((m) => m.id !== module.id);
      if (index === -1) return [...prev, module];
      return prev.map((m) => (m.id === module.id ? module : m));
    });
  }, []);

  const createModule = useCallback(
    async (input: ModuleCreateInput) => {
      const created = await libraryApi.createModule(input);
      upsertLocal(created);
      return created;
    },
    [upsertLocal],
  );

  const archiveModule = useCallback(async (id: string) => {
    await libraryApi.archiveModule(id);
    setModules((prev) => prev.filter((m) => m.id !== id));
  }, []);

  return { modules, loading, error, refresh, createModule, archiveModule, upsertLocal };
}
