import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('./supabaseClient', () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: { access_token: 'ops-token' } } }),
    },
    from: () => {
      throw new Error('supabase-js must not be used in this test');
    },
  },
  isSupabaseConfigured: true,
}));

import { adminApi } from './adminApi';

function jsonResponse(body, { ok = true, status = 200 } = {}) {
  return {
    ok,
    status,
    headers: { get: (name) => (name === 'content-type' ? 'application/json' : null) },
    json: async () => body,
  };
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('adminApi.extractJdFromPdf', () => {
  it('posts the file as multipart FormData without a JSON content type', async () => {
    const payload = { text: 'Senior Analyst JD', page_count: 2, char_count: 17, truncated: false };
    fetch.mockResolvedValue(jsonResponse(payload));

    const file = new File(['%PDF-fake'], 'jd.pdf', { type: 'application/pdf' });
    await expect(adminApi.extractJdFromPdf(file)).resolves.toEqual(payload);

    const [url, init] = fetch.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/packages\/jd\/extract-pdf$/);
    expect(init.method).toBe('POST');
    expect(init.headers.Authorization).toBe('Bearer ops-token');
    expect(init.headers['Content-Type']).toBeUndefined();
    expect(init.body).toBeInstanceOf(FormData);
    expect(init.body.get('file')).toBe(file);
  });

  it('surfaces the scanned-PDF 422 message verbatim', async () => {
    fetch.mockResolvedValue(
      jsonResponse(
        {
          detail:
            'No text could be extracted from this PDF. It looks scanned or image-only — paste the job description text instead.',
        },
        { ok: false, status: 422 },
      ),
    );

    const file = new File(['%PDF-fake'], 'scan.pdf', { type: 'application/pdf' });
    await expect(adminApi.extractJdFromPdf(file)).rejects.toThrow(/scanned or image-only/);
  });
});
