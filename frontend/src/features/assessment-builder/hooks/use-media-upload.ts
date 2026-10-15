import { useCallback, useEffect, useRef, useState } from 'react';
import { UploadError, classifyStorageError, uploadAssessmentMedia, validateMediaFile } from '../api/media-upload';
import type { MediaUploadResult, StorageClient } from '../api/media-upload';

export type UploadPhase =
  | { status: 'idle' }
  | { status: 'uploading'; fileName: string }
  | { status: 'success'; result: MediaUploadResult }
  | { status: 'error'; error: UploadError };

export interface MediaUploadState {
  phase: UploadPhase;
  upload: (file: File) => Promise<MediaUploadResult | null>;
  cancel: () => void;
  reset: () => void;
}

/**
 * Upload lifecycle for one drop zone. Any in-flight upload is aborted on
 * unmount so closing the editor never leaves a dangling request.
 *
 * @param moduleId - Module whose folder receives the asset.
 * @param storage - Optional injected storage client (tests).
 * @returns Phase state plus upload/cancel/reset actions.
 */
export function useMediaUpload(moduleId: string, storage?: StorageClient): MediaUploadState {
  const [phase, setPhase] = useState<UploadPhase>({ status: 'idle' });
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const upload = useCallback(
    async (file: File): Promise<MediaUploadResult | null> => {
      const invalid = validateMediaFile(file);
      if (invalid) {
        setPhase({ status: 'error', error: invalid });
        return null;
      }
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      setPhase({ status: 'uploading', fileName: file.name });
      try {
        const result = await uploadAssessmentMedia(file, { moduleId, storage, signal: controller.signal });
        if (controllerRef.current !== controller) return null;
        setPhase({ status: 'success', result });
        return result;
      } catch (err) {
        if (controllerRef.current !== controller) return null;
        setPhase({ status: 'error', error: classifyStorageError(err) });
        return null;
      } finally {
        if (controllerRef.current === controller) controllerRef.current = null;
      }
    },
    [moduleId, storage],
  );

  const cancel = useCallback(() => {
    const controller = controllerRef.current;
    if (!controller) return;
    controller.abort();
    controllerRef.current = null;
    setPhase({ status: 'error', error: new UploadError('aborted') });
  }, []);

  const reset = useCallback(() => setPhase({ status: 'idle' }), []);

  return { phase, upload, cancel, reset };
}
