import { useCallback, useEffect, useRef, useState } from 'react';
import { libraryApi } from '../api/library-api';
import type { AssessmentModuleDetail, ModuleSettings } from '../types/module';
import type { QuestionPayload, TemplateQuestion } from '../types/question';

export type PendingAction = 'settings' | 'publish' | 'clone' | 'question' | null;

export interface ModuleDetailState {
  module: AssessmentModuleDetail | null;
  loading: boolean;
  error: string | null;
  pending: PendingAction;
  reload: () => Promise<void>;
  saveSettings: (settings: ModuleSettings) => Promise<AssessmentModuleDetail>;
  publish: () => Promise<AssessmentModuleDetail>;
  cloneVersion: () => Promise<AssessmentModuleDetail>;
  saveQuestion: (payload: QuestionPayload, questionId: string | null) => Promise<TemplateQuestion>;
  removeQuestion: (questionId: string) => Promise<void>;
}

/**
 * Detail state for the module open in the editor drawer.
 *
 * Mutations rethrow after resetting `pending` so callers can branch on
 * `ApiError.isModuleLocked` and offer "Clone as New Version".
 *
 * @param moduleId - Module to load, or null when the drawer is closed.
 * @returns Module detail plus lifecycle and question actions.
 */
export function useModuleDetail(moduleId: string | null): ModuleDetailState {
  const [module, setModule] = useState<AssessmentModuleDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingAction>(null);
  const currentIdRef = useRef<string | null>(moduleId);

  const reload = useCallback(async () => {
    currentIdRef.current = moduleId;
    if (!moduleId) {
      setModule(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const detail = await libraryApi.getModule(moduleId);
      if (currentIdRef.current === moduleId) setModule(detail);
    } catch (err) {
      if (currentIdRef.current === moduleId) {
        setError(err instanceof Error ? err.message : 'Could not load this module.');
      }
    } finally {
      if (currentIdRef.current === moduleId) setLoading(false);
    }
  }, [moduleId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const run = useCallback(async <T,>(action: Exclude<PendingAction, null>, fn: () => Promise<T>): Promise<T> => {
    setPending(action);
    try {
      return await fn();
    } finally {
      setPending(null);
    }
  }, []);

  const requireId = useCallback((): string => {
    if (!moduleId) throw new Error('No module selected.');
    return moduleId;
  }, [moduleId]);

  const saveSettings = useCallback(
    (settings: ModuleSettings) =>
      run('settings', async () => {
        const detail = await libraryApi.updateSettings(requireId(), settings);
        setModule(detail);
        return detail;
      }),
    [requireId, run],
  );

  const publish = useCallback(
    () =>
      run('publish', async () => {
        const detail = await libraryApi.publishModule(requireId());
        setModule(detail);
        return detail;
      }),
    [requireId, run],
  );

  const cloneVersion = useCallback(
    () => run('clone', () => libraryApi.cloneVersion(requireId())),
    [requireId, run],
  );

  const saveQuestion = useCallback(
    (payload: QuestionPayload, questionId: string | null) =>
      run('question', async () => {
        const id = requireId();
        const saved = questionId
          ? await libraryApi.updateQuestion(id, questionId, payload)
          : await libraryApi.createQuestion(id, payload);
        await reload();
        return saved;
      }),
    [reload, requireId, run],
  );

  const removeQuestion = useCallback(
    (questionId: string) =>
      run('question', async () => {
        await libraryApi.deactivateQuestion(requireId(), questionId);
        await reload();
      }),
    [reload, requireId, run],
  );

  return { module, loading, error, pending, reload, saveSettings, publish, cloneVersion, saveQuestion, removeQuestion };
}
