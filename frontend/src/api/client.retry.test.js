import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  EXAM_REQUEST_TIMEOUT_MS,
  api,
  fetchWithTimeout,
  isRetryableRequestError,
  withRetry,
} from './client';

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('exam-path request hardening (P1-02)', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('aborts a stalled request after 15s with a retryable TIMEOUT error', async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url, init) =>
          new Promise((_resolve, reject) => {
            init.signal.addEventListener('abort', () =>
              reject(new DOMException('aborted', 'AbortError')),
            );
          }),
      ),
    );
    const pending = fetchWithTimeout('/x', {});
    const assertion = expect(pending).rejects.toMatchObject({ code: 'TIMEOUT', retryable: true });
    await vi.advanceTimersByTimeAsync(EXAM_REQUEST_TIMEOUT_MS);
    await assertion;
  });

  it('retries only transport failures and gateway statuses', () => {
    expect(isRetryableRequestError({ retryable: true })).toBe(true);
    expect(isRetryableRequestError({ status: 503 })).toBe(true);
    expect(isRetryableRequestError({ status: 409, code: 'ALREADY_SUBMITTED' })).toBe(false);
    expect(isRetryableRequestError({ status: 422 })).toBe(false);
  });

  it('backs off exponentially and gives up after the retry budget', async () => {
    vi.useFakeTimers();
    const attempt = vi.fn(async () => {
      const err = new Error('down');
      err.status = 503;
      throw err;
    });
    const run = withRetry(attempt, { retries: 2, baseMs: 1000 });
    const assertion = expect(run).rejects.toMatchObject({ status: 503 });
    await vi.advanceTimersByTimeAsync(0);
    expect(attempt).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(attempt).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(2000);
    expect(attempt).toHaveBeenCalledTimes(3);
    await assertion;
  });

  it('submit retries a dropped connection and then succeeds', async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce(jsonResponse({ status: 'COMPLETED', package_complete: false }));
    vi.stubGlobal('fetch', fetchMock);
    const run = api.candidate.submitTest('a1', []);
    await vi.advanceTimersByTimeAsync(1000);
    await expect(run).resolves.toMatchObject({ status: 200, package_complete: false });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('does not retry a 409 ALREADY_SUBMITTED', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ detail: { code: 'ALREADY_SUBMITTED', message: 'done' } }, 409),
    );
    vi.stubGlobal('fetch', fetchMock);
    await expect(api.candidate.submitTest('a1', [])).rejects.toMatchObject({
      status: 409,
      code: 'ALREADY_SUBMITTED',
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('sends keepalive autosaves once, with keepalive set on the request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: 'r1' }));
    vi.stubGlobal('fetch', fetchMock);
    await api.candidate.autosave({ question_id: 'q1' }, { keepalive: true });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][1].keepalive).toBe(true);
  });
});
