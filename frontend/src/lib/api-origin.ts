/**
 * Resolves the origin prefix for FastAPI calls (paths already start with `/api`).
 *
 * Production builds only honour an explicit HTTPS origin; anything else collapses
 * to same-origin so requests flow through the Cloudflare Pages `/api/*` proxy
 * instead of tripping mixed-content and CSP `connect-src 'self'` blocks.
 */
export function resolveApiOrigin(configured: string | undefined, isProd: boolean): string {
  const value = (configured ?? '').trim().replace(/\/+$/, '');
  if (!value) return '';
  if (isProd && !value.startsWith('https://')) return '';
  return value;
}

export const API_ORIGIN: string = resolveApiOrigin(import.meta.env.VITE_API_URL, import.meta.env.PROD);
