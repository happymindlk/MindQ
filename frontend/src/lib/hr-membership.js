import { API_ORIGIN } from './api-origin';
import { requestJson } from './api-request';

/**
 * Source of truth for tenant membership is public.hr_users, read server-side by
 * `GET /api/v1/auth/me` (subject taken from the verified access token).
 * JWT app_metadata.corporate_id is a cache populated by the custom access token hook
 * and can be stale until refreshSession() after SQL provisioning.
 *
 * The token is passed in rather than read via supabase.auth.getSession() so this
 * is safe to call from onAuthStateChange handlers.
 *
 * @param {{ access_token?: string, user?: { id?: string } } | null | undefined} activeSession
 * @returns {Promise<{ user_id: string, corporate_id: string, role: string, full_name: string | null } | null>}
 */
export async function fetchHrMembership(activeSession) {
  const userId = activeSession?.user?.id;
  const token = activeSession?.access_token;
  if (!userId || !token) return null;
  try {
    const data = await requestJson(
      `${API_ORIGIN}/api/v1/auth/me`,
      { headers: { Authorization: `Bearer ${token}` } },
      'Failed to load account membership',
    );
    // Guard against a response for a different (previous) session.
    if (!data || data.user_id !== userId) return null;
    return data;
  } catch (error) {
    console.error('hr_users membership fetch failed:', error?.message);
    throw error;
  }
}
