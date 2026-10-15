// Same-origin fallback proxy for /api/*, used only when the build leaves VITE_API_URL
// empty. Override the target with the BACKEND_ORIGIN Pages env var. Workers reject
// subrequests to raw IP addresses (error 1003), so this must be a DNS hostname.
const DEFAULT_BACKEND_ORIGIN = 'https://api-qa.mindqtalent.com';

const HOP_BY_HOP_HEADERS = [
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
  'host',
];

const BODYLESS_METHODS = new Set(['GET', 'HEAD']);

/**
 * @param {{ request: Request, env: { BACKEND_ORIGIN?: string } }} context
 * @returns {Promise<Response>}
 */
export async function onRequest({ request, env }) {
  const backendOrigin = (env.BACKEND_ORIGIN || DEFAULT_BACKEND_ORIGIN).replace(/\/+$/, '');
  const url = new URL(request.url);
  const target = `${backendOrigin}${url.pathname}${url.search}`;

  const headers = new Headers(request.headers);
  for (const name of HOP_BY_HOP_HEADERS) headers.delete(name);
  headers.set('X-Forwarded-Proto', url.protocol.replace(':', ''));
  headers.set('X-Forwarded-Host', url.host);

  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body: BODYLESS_METHODS.has(request.method) ? undefined : request.body,
    });
    return new Response(upstream.body, upstream);
  } catch (error) {
    console.error(JSON.stringify({ event: 'api_proxy_upstream_error', target, message: String(error) }));
    return Response.json(
      { detail: { code: 'UPSTREAM_UNAVAILABLE', message: 'Backend service is unreachable.' } },
      { status: 502 },
    );
  }
}
