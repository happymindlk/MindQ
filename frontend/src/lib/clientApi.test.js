import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { clientApi, ClientAuthError } from './clientApi';
import {
  clearClientSession,
  readClientSession,
  writeClientSession,
} from '../pages/client/client-session';

function jsonResponse(body, { ok = true, status = 200 } = {}) {
  return { ok, status, json: async () => body };
}

beforeEach(() => {
  clearClientSession();
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('clientApi.requestOtp', () => {
  it('posts the email to the FastAPI HR OTP send endpoint and returns the temp token', async () => {
    fetch.mockResolvedValue(jsonResponse({ status: 'otp_required', temp_token: 'temp-token-value' }));

    await expect(clientApi.requestOtp('hr@acme.test')).resolves.toBe('temp-token-value');

    const [url, init] = fetch.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/hr\/auth\/otp\/send$/);
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ email: 'hr@acme.test' });
  });

  it('fails fast when the challenge response has no temp token', async () => {
    fetch.mockResolvedValue(jsonResponse({ status: 'otp_required' }));
    await expect(clientApi.requestOtp('hr@acme.test')).rejects.toThrow(/did not return a session/);
  });

  it('surfaces backend errors verbatim', async () => {
    fetch.mockResolvedValue(
      jsonResponse(
        { detail: 'This email is not registered for the client portal' },
        { ok: false, status: 403 },
      ),
    );
    await expect(clientApi.requestOtp('ghost@acme.test')).rejects.toThrow('not registered');
  });
});

describe('clientApi.verifyOtp', () => {
  it('posts email, code, and temp token to verify and stores the backend client session', async () => {
    fetch.mockResolvedValue(
      jsonResponse({
        access_token: 'client-jwt',
        token_type: 'bearer',
        expires_in: 3600,
        corporate: { id: 'corp-1', name: 'Acme', logo_url: null },
        user: { id: 'u1', email: 'hr@acme.test', full_name: 'Harriet', role: 'hr', corporate_id: 'corp-1' },
      }),
    );

    const session = await clientApi.verifyOtp('hr@acme.test', '123456', 'temp-token-value');

    const [url, init] = fetch.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/hr\/auth\/otp\/verify$/);
    expect(JSON.parse(init.body)).toEqual({
      email: 'hr@acme.test',
      otp_code: '123456',
      temp_token: 'temp-token-value',
    });
    expect(session.token).toBe('client-jwt');
    expect(session.corporate).toEqual({ id: 'corp-1', name: 'Acme', logo_url: null });
    expect(readClientSession()?.token).toBe('client-jwt');
  });

  it('does not store a session when the code is rejected', async () => {
    fetch.mockResolvedValue(
      jsonResponse({ detail: 'Invalid or expired verification code' }, { ok: false, status: 401 }),
    );
    await expect(clientApi.verifyOtp('hr@acme.test', '000000', 'temp-token-value')).rejects.toThrow(
      'Invalid or expired verification code',
    );
    expect(readClientSession()).toBeNull();
  });
});

describe('clientApi.downloadReport', () => {
  function pdfResponse(headers, { ok = true, status = 200 } = {}) {
    return {
      ok,
      status,
      headers: new Headers(headers),
      blob: async () => new Blob(['%PDF'], { type: 'application/pdf' }),
      json: async () => ({ detail: 'Candidate not found' }),
    };
  }

  let anchor;

  beforeEach(() => {
    writeClientSession({ access_token: 'client-jwt', expires_in: 3600, corporate: { id: 'c1' } });
    window.URL.createObjectURL = vi.fn(() => 'blob:report');
    window.URL.revokeObjectURL = vi.fn();
    anchor = null;
    const createElement = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tag) => {
      const el = createElement(tag);
      if (tag === 'a') {
        anchor = el;
        vi.spyOn(el, 'click').mockImplementation(() => {});
      }
      return el;
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('downloads the server PDF with the client JWT and returns cache metadata', async () => {
    fetch.mockResolvedValue(
      pdfResponse({
        'content-type': 'application/pdf',
        'content-disposition':
          'attachment; filename="MindQ Report - Pat Lee.pdf"; filename*=UTF-8\'\'MindQ%20Report%20-%20Pat%20Lee.pdf',
        'x-report-type': 'PDF',
        'x-report-synthesis-status': 'ok',
        'x-report-cache': 'HIT',
      }),
    );

    await expect(clientApi.downloadReport('cand 1')).resolves.toEqual({
      isHtml: false,
      synthesisStatus: 'ok',
      cacheState: 'HIT',
    });

    const [url, init] = fetch.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/client\/candidates\/cand%201\/report$/);
    expect(init.headers.Authorization).toBe('Bearer client-jwt');
    expect(anchor.download).toBe('MindQ Report - Pat Lee.pdf');
    expect(anchor.href).toBe('blob:report');
    expect(anchor.click).toHaveBeenCalledOnce();
  });

  it('reports a generating narrative and HTML fallback', async () => {
    fetch.mockResolvedValue(
      pdfResponse({
        'content-type': 'text/html',
        'x-report-type': 'HTML',
        'x-report-synthesis-status': 'generating',
        'x-report-cache': 'BYPASS',
      }),
    );
    const result = await clientApi.downloadReport('cand-1');
    expect(result).toEqual({ isHtml: true, synthesisStatus: 'generating', cacheState: 'BYPASS' });
    expect(anchor.download).toBe('MindQ Report - cand-1.html');
  });

  it('clears an expired session on 401 without downloading', async () => {
    const expired = vi.fn();
    window.addEventListener('client-session-expired', expired);
    fetch.mockResolvedValue(pdfResponse({}, { ok: false, status: 401 }));

    await expect(clientApi.downloadReport('cand-1')).rejects.toBeInstanceOf(ClientAuthError);
    expect(readClientSession()).toBeNull();
    expect(expired).toHaveBeenCalledOnce();
    expect(anchor).toBeNull();
    window.removeEventListener('client-session-expired', expired);
  });

  it('surfaces a 404 for another tenant\'s candidate', async () => {
    fetch.mockResolvedValue(pdfResponse({}, { ok: false, status: 404 }));
    await expect(clientApi.downloadReport('cand-1')).rejects.toThrow('Candidate not found');
    expect(anchor).toBeNull();
  });

  it('refuses to call the API without a session', async () => {
    clearClientSession();
    await expect(clientApi.downloadReport('cand-1')).rejects.toBeInstanceOf(ClientAuthError);
    expect(fetch).not.toHaveBeenCalled();
  });
});
