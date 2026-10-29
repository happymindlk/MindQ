/**
 * Normalize question media URLs so candidate browsers can load them.
 *
 * Admin uploads often persist a local Supabase origin (`http://127.0.0.1:54321/...`)
 * that is unreachable from deployed portals. Rewrite those hosts (and bare storage
 * paths) to the configured `VITE_SUPABASE_URL` public origin.
 *
 * @param mediaUrl - Raw `media_url` from the runner / candidate API.
 * @param supabaseUrl - Public Supabase origin; defaults to `VITE_SUPABASE_URL`.
 * @returns Absolute URL candidates can fetch, or null when blank.
 */
export function resolveAssessmentMediaUrl(
  mediaUrl: string | null | undefined,
  supabaseUrl: string | undefined = import.meta.env.VITE_SUPABASE_URL,
): string | null {
  if (mediaUrl == null) return null;
  const raw = mediaUrl.trim();
  if (!raw) return null;

  const base = (supabaseUrl ?? '').trim().replace(/\/+$/, '');

  if (raw.startsWith('http://') || raw.startsWith('https://')) {
    try {
      const parsed = new URL(raw);
      const isAssessmentMedia = parsed.pathname.includes('/storage/v1/object/public/assessment-media/');
      const isLocalHost = parsed.hostname === '127.0.0.1' || parsed.hostname === 'localhost';
      if (isLocalHost && isAssessmentMedia && base) {
        return `${base}${parsed.pathname}${parsed.search}`;
      }
      return raw;
    } catch {
      return raw;
    }
  }

  if (raw.startsWith('assets/')) return `/${raw}`;
  if (raw.startsWith('/assets/')) return raw;

  if (!base) return raw;

  if (raw.startsWith('/storage/v1/object/public/assessment-media/')) {
    return `${base}${raw}`;
  }
  if (raw.startsWith('assessment-media/')) {
    return `${base}/storage/v1/object/public/${raw}`;
  }
  if (raw.startsWith('modules/')) {
    return `${base}/storage/v1/object/public/assessment-media/${raw}`;
  }
  return raw;
}
