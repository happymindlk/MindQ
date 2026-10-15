import { supabase } from '../../../lib/supabaseClient';

export const MEDIA_BUCKET = 'assessment-media';
export const MAX_MEDIA_BYTES = 5 * 1024 * 1024;

/** Mirrors the bucket's `allowed_mime_types`. SVG is excluded (script-capable). */
export const ALLOWED_MEDIA_TYPES: Readonly<Record<string, string>> = {
  'image/png': 'png',
  'image/jpeg': 'jpg',
  'image/webp': 'webp',
};

export type UploadErrorCode = 'too_large' | 'bad_type' | 'unauthorized' | 'network' | 'aborted' | 'unknown';

export const UPLOAD_ERROR_MESSAGES: Record<UploadErrorCode, string> = {
  too_large: 'Image exceeds the 5 MB limit. Compress it and retry.',
  bad_type: 'Only PNG, JPEG, or WebP images are supported.',
  unauthorized: 'Your session cannot write to assessment media. Sign in again as an admin.',
  network: 'Upload failed due to a network error. Check your connection and retry.',
  aborted: 'Upload cancelled.',
  unknown: 'Upload failed. Retry, or contact support if this keeps happening.',
};

export class UploadError extends Error {
  readonly code: UploadErrorCode;

  constructor(code: UploadErrorCode, message: string = UPLOAD_ERROR_MESSAGES[code]) {
    super(message);
    this.name = 'UploadError';
    this.code = code;
  }
}

/** Minimal Storage surface used here, so tests can inject a fake client. */
export interface StorageError {
  message: string;
  statusCode?: string | number;
  status?: number;
  error?: string;
}

export interface StorageBucketApi {
  upload(
    path: string,
    file: File,
    options: { cacheControl: string; contentType: string; upsert: boolean },
  ): Promise<{ data: { path: string } | null; error: StorageError | null }>;
  getPublicUrl(path: string): { data: { publicUrl: string } };
  remove(paths: string[]): Promise<{ data: unknown; error: StorageError | null }>;
}

export interface StorageClient {
  from(bucket: string): StorageBucketApi;
}

export interface MediaUploadResult {
  path: string;
  publicUrl: string;
}

export interface UploadOptions {
  moduleId: string;
  storage?: StorageClient;
  signal?: AbortSignal;
  createId?: () => string;
}

/**
 * Validate a file against the bucket constraints before any network call.
 *
 * @param file - Candidate file from drop or picker.
 * @returns UploadError when invalid, otherwise null.
 */
export function validateMediaFile(file: File): UploadError | null {
  if (!(file.type in ALLOWED_MEDIA_TYPES)) return new UploadError('bad_type');
  if (file.size > MAX_MEDIA_BYTES) return new UploadError('too_large');
  if (file.size === 0) return new UploadError('unknown', 'The selected file is empty.');
  return null;
}

/**
 * Map a Supabase Storage error onto a typed UploadError.
 *
 * @param error - Error object returned by storage-js (or a thrown fetch error).
 * @returns Typed UploadError.
 */
export function classifyStorageError(error: unknown): UploadError {
  if (error instanceof UploadError) return error;
  if (error instanceof DOMException && error.name === 'AbortError') return new UploadError('aborted');
  if (error instanceof TypeError) return new UploadError('network');
  const record = (typeof error === 'object' && error !== null ? error : {}) as Partial<StorageError>;
  const status = Number(record.statusCode ?? record.status ?? NaN);
  const message = String(record.message ?? '').toLowerCase();
  if (status === 413 || message.includes('maximum allowed size') || message.includes('too large')) {
    return new UploadError('too_large');
  }
  if (status === 415 || message.includes('mime type') || message.includes('invalid_mime')) {
    return new UploadError('bad_type');
  }
  if (status === 401 || status === 403 || message.includes('row-level security') || message.includes('unauthorized')) {
    return new UploadError('unauthorized');
  }
  if (message.includes('failed to fetch') || message.includes('network')) {
    return new UploadError('network');
  }
  return new UploadError('unknown');
}

function defaultId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw new UploadError('aborted');
}

/**
 * Upload a cognitive puzzle asset to `assessment-media` and return its public URL.
 *
 * Objects are immutable (`upsert: false`, random names) so a published question's
 * `media_url` can never be overwritten in place. Network failures are retried once.
 *
 * @param file - Image to upload.
 * @param options - Target module, optional injected storage client and abort signal.
 * @returns Storage path and public URL for the question's `media_url`.
 * @throws UploadError with a typed `code` on any failure.
 */
export async function uploadAssessmentMedia(
  file: File,
  { moduleId, storage = supabase.storage as unknown as StorageClient, signal, createId = defaultId }: UploadOptions,
): Promise<MediaUploadResult> {
  const invalid = validateMediaFile(file);
  if (invalid) throw invalid;
  throwIfAborted(signal);

  const ext = ALLOWED_MEDIA_TYPES[file.type] ?? 'bin';
  const path = `modules/${moduleId}/${createId()}.${ext}`;
  const bucket = storage.from(MEDIA_BUCKET);

  let lastError: UploadError | null = null;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    throwIfAborted(signal);
    try {
      const { data, error } = await bucket.upload(path, file, {
        cacheControl: '31536000',
        contentType: file.type,
        upsert: false,
      });
      if (error) {
        lastError = classifyStorageError(error);
      } else {
        const storedPath = data?.path ?? path;
        if (signal?.aborted) {
          // Upload landed after the user cancelled; remove it so no orphan remains.
          await bucket.remove([storedPath]);
          throw new UploadError('aborted');
        }
        const { data: urlData } = bucket.getPublicUrl(storedPath);
        if (!urlData.publicUrl) throw new UploadError('unknown', 'Storage returned no public URL.');
        return { path: storedPath, publicUrl: urlData.publicUrl };
      }
    } catch (err) {
      lastError = classifyStorageError(err);
      if (lastError.code === 'aborted') throw lastError;
    }
    if (!lastError || lastError.code !== 'network') break;
  }
  throw lastError ?? new UploadError('unknown');
}
