import { ApiError, toApiError } from './api-error';

export const NETWORK_ERROR_MESSAGE =
  'Unable to reach the server. Check your connection and try again.';
export const BAD_RESPONSE_MESSAGE = 'The server returned an unexpected response. Please try again.';

/** In-flight GET/HEAD promises keyed by method + url + Authorization. */
const inflightGets = new Map<string, Promise<Response>>();

/**
 * Build a coalesce key for safe GET/HEAD dedupe, or null when coalescing is unsafe.
 *
 * Skips mutations and any request carrying an AbortSignal so zip/PDF aborts stay
 * independent. Authorization is part of the key so sessions never share bodies.
 *
 * @param url - Absolute or same-origin URL.
 * @param init - Standard fetch options.
 * @returns Coalesce key, or null when this call must hit the network alone.
 */
function coalesceKey(url: string, init: RequestInit | undefined): string | null {
  const method = (init?.method ?? 'GET').toUpperCase();
  if (method !== 'GET' && method !== 'HEAD') return null;
  if (init?.signal) return null;
  const headers = new Headers(init?.headers);
  const auth = headers.get('Authorization') ?? '';
  return `${method}\0${url}\0${auth}`;
}

/** Clear the inflight map (tests only). */
export function resetApiFetchInflight(): void {
  inflightGets.clear();
}

/**
 * Hand each waiter an independent body stream when the runtime supports clone.
 * Test doubles often omit `clone`; fall back to the shared Response then.
 *
 * @param res - Successful fetch Response.
 * @returns Cloned Response, or the original when clone is unavailable.
 */
function shareResponse(res: Response): Response {
  if (typeof res.clone === 'function') {
    try {
      return res.clone();
    } catch {
      return res;
    }
  }
  return res;
}

/**
 * `fetch` that never rejects with a raw TypeError: offline, DNS, TLS, CORS and CSP
 * failures surface as an `ApiError` with code `NETWORK`, and non-ok responses as
 * an `ApiError` carrying the parsed FastAPI detail.
 *
 * Concurrent identical GET/HEAD calls (same URL + Authorization, no AbortSignal)
 * share one network round-trip; each waiter receives `response.clone()` when available.
 *
 * @param url - Absolute or same-origin URL.
 * @param init - Standard fetch options.
 * @param fallback - Message used when the error body carries nothing readable.
 * @returns The ok Response, body unread.
 */
export async function apiFetch(url: string, init: RequestInit, fallback: string): Promise<Response> {
  const key = coalesceKey(url, init);

  const run = async (): Promise<Response> => {
    let res: Response;
    try {
      res = await fetch(url, init);
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') throw err;
      throw new ApiError(NETWORK_ERROR_MESSAGE, 0, 'NETWORK', String(err));
    }
    if (!res.ok) throw await toApiError(res, fallback);
    return res;
  };

  if (!key) {
    return run();
  }

  const existing = inflightGets.get(key);
  if (existing) {
    return shareResponse(await existing);
  }

  const pending = run().finally(() => {
    inflightGets.delete(key);
  });
  inflightGets.set(key, pending);
  return shareResponse(await pending);
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
