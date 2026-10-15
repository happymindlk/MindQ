import { describe, expect, it, vi } from 'vitest';

vi.mock('../../../lib/supabaseClient', () => ({ supabase: { storage: {} } }));

import { MAX_MEDIA_BYTES, UploadError, classifyStorageError, uploadAssessmentMedia } from './media-upload';
import type { StorageBucketApi, StorageClient, StorageError } from './media-upload';

type UploadResult = Awaited<ReturnType<StorageBucketApi['upload']>>;

function fakeStorage(results: Array<UploadResult | Error>) {
  const queue = [...results];
  const bucket = {
    upload: vi.fn(async (): Promise<UploadResult> => {
      const next = queue.shift();
      if (!next) throw new Error('no more results');
      if (next instanceof Error) throw next;
      return next;
    }),
    getPublicUrl: vi.fn((path: string) => ({ data: { publicUrl: `https://cdn.test/${path}` } })),
    remove: vi.fn(async () => ({ data: null, error: null })),
  };
  const storage: StorageClient = { from: vi.fn(() => bucket) };
  return { storage, bucket };
}

function png(size = 1024, type = 'image/png'): File {
  const file = new File([new Uint8Array(1)], 'puzzle.png', { type });
  Object.defineProperty(file, 'size', { value: size });
  return file;
}

const ok = (path: string): UploadResult => ({ data: { path }, error: null });
const fail = (error: StorageError): UploadResult => ({ data: null, error });

describe('uploadAssessmentMedia', () => {
  it('uploads immutably under the module folder and returns the public URL', async () => {
    const { storage, bucket } = fakeStorage([ok('modules/m1/abc.png')]);
    const result = await uploadAssessmentMedia(png(), { moduleId: 'm1', storage, createId: () => 'abc' });
    expect(bucket.upload).toHaveBeenCalledWith(
      'modules/m1/abc.png',
      expect.any(File),
      expect.objectContaining({ upsert: false, contentType: 'image/png' }),
    );
    expect(result).toEqual({ path: 'modules/m1/abc.png', publicUrl: 'https://cdn.test/modules/m1/abc.png' });
  });

  it.each([
    ['too_large', png(MAX_MEDIA_BYTES + 1)],
    ['bad_type', png(10, 'image/svg+xml')],
  ])('rejects %s before any network call', async (code, file) => {
    const { storage, bucket } = fakeStorage([]);
    await expect(uploadAssessmentMedia(file, { moduleId: 'm1', storage })).rejects.toMatchObject({ code });
    expect(bucket.upload).not.toHaveBeenCalled();
  });

  it('maps RLS / 403 errors to unauthorized without retrying', async () => {
    const { storage, bucket } = fakeStorage([fail({ message: 'new row violates row-level security policy', statusCode: '403' })]);
    await expect(uploadAssessmentMedia(png(), { moduleId: 'm1', storage })).rejects.toMatchObject({ code: 'unauthorized' });
    expect(bucket.upload).toHaveBeenCalledTimes(1);
  });

  it('retries a network failure once and then succeeds', async () => {
    const { storage, bucket } = fakeStorage([new TypeError('Failed to fetch'), ok('modules/m1/x.png')]);
    const result = await uploadAssessmentMedia(png(), { moduleId: 'm1', storage, createId: () => 'x' });
    expect(bucket.upload).toHaveBeenCalledTimes(2);
    expect(result.publicUrl).toContain('x.png');
  });

  it('gives up after the second network failure', async () => {
    const { storage } = fakeStorage([new TypeError('Failed to fetch'), new TypeError('Failed to fetch')]);
    await expect(uploadAssessmentMedia(png(), { moduleId: 'm1', storage })).rejects.toMatchObject({ code: 'network' });
  });

  it('removes the object when the user cancelled while the upload was landing', async () => {
    const controller = new AbortController();
    const { storage, bucket } = fakeStorage([]);
    bucket.upload.mockImplementationOnce(async () => {
      controller.abort();
      return ok('modules/m1/late.png');
    });
    await expect(
      uploadAssessmentMedia(png(), { moduleId: 'm1', storage, signal: controller.signal }),
    ).rejects.toMatchObject({ code: 'aborted' });
    expect(bucket.remove).toHaveBeenCalledWith(['modules/m1/late.png']);
  });
});

describe('classifyStorageError', () => {
  it.each([
    [{ message: 'The object exceeded the maximum allowed size', statusCode: '413' }, 'too_large'],
    [{ message: 'mime type image/gif is not supported', statusCode: '415' }, 'bad_type'],
    [{ message: 'Something odd' }, 'unknown'],
    [new DOMException('aborted', 'AbortError'), 'aborted'],
  ])('maps %o to %s', (error, code) => {
    expect(classifyStorageError(error).code).toBe(code);
  });

  it('passes UploadError through unchanged', () => {
    const original = new UploadError('network');
    expect(classifyStorageError(original)).toBe(original);
  });
});
