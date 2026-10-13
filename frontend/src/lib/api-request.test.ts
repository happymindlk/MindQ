import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './api-error';
import { BAD_RESPONSE_MESSAGE, NETWORK_ERROR_MESSAGE, apiFetch, requestJson } from './api-request';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

async function rejection(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (err) {
    expect(err).toBeInstanceOf(ApiError);
    return err as ApiError;
  }
  throw new Error('expected promise to reject');
}

describe('requestJson', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('returns decoded JSON for a successful response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse([{ id: 'c1' }])));
    await expect(requestJson('/api/v1/packages/corporates', {}, 'fallback')).resolves.toEqual([
      { id: 'c1' },
    ]);
  });

  it('maps a rejected fetch (offline, CORS, CSP block) to a NETWORK ApiError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    const err = await rejection(requestJson('/api/x', {}, 'fallback'));
    expect(err.code).toBe('NETWORK');
    expect(err.status).toBe(0);
    expect(err.isNetworkError).toBe(true);
    expect(err.message).toBe(NETWORK_ERROR_MESSAGE);
  });

  it('rethrows aborts untouched so callers can ignore cancelled requests', async () => {
    const abort = new DOMException('aborted', 'AbortError');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(abort));
    await expect(apiFetch('/api/x', {}, 'fallback')).rejects.toBe(abort);
  });

  it('surfaces structured {detail: {code, message}} errors, e.g. the Pages proxy 502', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          { detail: { code: 'UPSTREAM_UNAVAILABLE', message: 'Backend service is unreachable.' } },
          502,
        ),
      ),
    );
    const err = await rejection(requestJson('/api/x', {}, 'fallback'));
    expect(err.status).toBe(502);
    expect(err.code).toBe('UPSTREAM_UNAVAILABLE');
    expect(err.message).toBe('Backend service is unreachable.');
  });

  it('uses the fallback when an error body is not JSON (e.g. Cloudflare 5xx HTML page)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response('<html>Bad gateway</html>', { status: 530, headers: { 'Content-Type': 'text/html' } }),
      ),
    );
    const err = await rejection(requestJson('/api/x', {}, 'Failed to load companies'));
    expect(err.status).toBe(530);
    expect(err.message).toBe('Failed to load companies');
  });

  it('rejects a 200 HTML body (SPA fallback when /api is not routed) as BAD_RESPONSE', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response('<!doctype html><div id="root"></div>', {
          status: 200,
          headers: { 'Content-Type': 'text/html' },
        }),
      ),
    );
    const err = await rejection(requestJson('/api/x', {}, 'fallback'));
    expect(err.code).toBe('BAD_RESPONSE');
    expect(err.message).toBe(BAD_RESPONSE_MESSAGE);
  });

  it('rejects malformed JSON with a JSON content type as BAD_RESPONSE', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response('{"truncated', { status: 200, headers: { 'Content-Type': 'application/json' } }),
      ),
    );
    const err = await rejection(requestJson('/api/x', {}, 'fallback'));
    expect(err.code).toBe('BAD_RESPONSE');
  });

  it('returns null for 204 No Content', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(requestJson('/api/x', { method: 'DELETE' }, 'fallback')).resolves.toBeNull();
  });
});
