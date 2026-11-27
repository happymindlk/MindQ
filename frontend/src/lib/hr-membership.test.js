import { afterEach, describe, expect, it, vi } from 'vitest';
import { resetApiFetchInflight } from './api-request';
import { fetchHrMembership } from './hr-membership';

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => body,
  };
}

const session = { access_token: 'tok-1', user: { id: 'user-1' } };

describe('fetchHrMembership', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    resetApiFetchInflight();
  });

  it('calls /api/v1/auth/me with the session bearer token', async () => {
    const membership = { user_id: 'user-1', corporate_id: 'corp-1', role: 'admin', full_name: 'Ops' };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(membership));
    vi.stubGlobal('fetch', fetchMock);

    await expect(fetchHrMembership(session)).resolves.toEqual(membership);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/auth\/me$/);
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer tok-1');
  });

  it('returns null when the user has no membership', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(null)));

    await expect(fetchHrMembership(session)).resolves.toBeNull();
  });

  it('ignores a membership for a different user', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ user_id: 'other', corporate_id: 'c', role: 'hr' })),
    );

    await expect(fetchHrMembership(session)).resolves.toBeNull();
  });

  it('skips the request without a session token', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    await expect(fetchHrMembership(null)).resolves.toBeNull();
    await expect(fetchHrMembership({ user: { id: 'user-1' } })).resolves.toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('rejects on API errors so callers can fall back to JWT claims', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail: 'Invalid or expired token' }, 401)));

    await expect(fetchHrMembership(session)).rejects.toThrow();
  });
});
