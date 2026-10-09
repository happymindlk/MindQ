/**
 * Masks the local part of an email for display on a locked screen.
 *
 * @param {string | null | undefined} email
 * @returns {string} e.g. `j***@acme.com`; non-email input is returned unchanged.
 */
export function maskEmail(email) {
  if (!email || !email.includes('@')) return email || '';
  const at = email.lastIndexOf('@');
  const local = email.slice(0, at);
  const domain = email.slice(at + 1);
  return `${local.slice(0, 1)}${'*'.repeat(Math.max(2, local.length - 1))}@${domain}`;
}
