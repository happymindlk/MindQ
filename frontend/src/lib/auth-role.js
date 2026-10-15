const OPS_ROLES = ['admin', 'owner'];

/**
 * Resolve tenant role from hr_users first, then JWT app_metadata.
 *
 * @param {object | null} session
 * @param {{ role?: string } | null} profile
 * @returns {string | null}
 */
export function resolveRole(session, profile) {
  return (
    profile?.role
    || session?.user?.app_metadata?.corporate_role
    || session?.user?.app_metadata?.role
    || null
  );
}

/**
 * Internal operators (ops/admin portal). HR stays on /client/*.
 *
 * @param {string | null | undefined} role
 * @returns {boolean}
 */
export function isOpsRole(role) {
  return OPS_ROLES.includes(role || '');
}
