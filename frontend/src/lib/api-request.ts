import { ApiError, toApiError } from './api-error';

export const NETWORK_ERROR_MESSAGE =
  'Unable to reach the server. Check your connection and try again.';
export const BAD_RESPONSE_MESSAGE = 'The server returned an unexpected response. Please try again.';

/**
 * `fetch` that never rejects with a raw TypeError: offline, DNS, TLS, CORS and CSP
 * failures surface as an `ApiError` with code `NETWORK`, and non-ok responses as
 * an `ApiError` carrying the parsed FastAPI detail.
 *
 * @param url - Absolute or same-origin URL.
 * @param init - Standard fetch options.
 * @param fallback - Message used when the error body carries nothing readable.
 * @returns The ok Response, body unread.
 */
export async function apiFetch(url: string, init: RequestInit, fallback: string): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err;
    throw new ApiError(NETWORK_ERROR_MESSAGE, 0, 'NETWORK', String(err));
  }
  if (!res.ok) throw await toApiError(res, fallback);
  return res;
}

/**
 * `apiFetch` plus JSON decoding. A 2xx body that is not JSON (e.g. an HTML page
 * served because `/api` was not routed to the backend) becomes a `BAD_RESPONSE`
 * error instead of a SyntaxError deep inside a component.
 *
 * @param url - Absolute or same-origin URL.
 * @param init - Standard fetch options.
 * @param fallback - Message used when the error body carries nothing readable.
 * @returns Decoded JSON, or `null` for 204 No Content.
 */
export async function requestJson<T>(url: string, init: RequestInit, fallback: string): Promise<T> {
  const res = await apiFetch(url, init, fallback);
  if (res.status === 204) return null as T;
  const contentType = res.headers.get('content-type') ?? '';
  if (!contentType.includes('json')) {
    throw new ApiError(BAD_RESPONSE_MESSAGE, res.status, 'BAD_RESPONSE', contentType);
  }
  try {
    return (await res.json()) as T;
  } catch (err) {
    throw new ApiError(BAD_RESPONSE_MESSAGE, res.status, 'BAD_RESPONSE', String(err));
  }
}
