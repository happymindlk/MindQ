export const SUPPORT_EMAIL = 'support@mindqtalent.com';

/** Details support needs to locate the candidate's attempt. */
export interface SupportContext {
  fullName: string | null;
  packageCode: string | null;
  userAgent: string;
  pagePath: string;
}

const PLACEHOLDER = '(please fill in)';

function field(value: string | null): string {
  const trimmed = (value ?? '').trim();
  return trimmed || PLACEHOLDER;
}

/**
 * Build a `mailto:` link pre-filled with everything the candidate already has,
 * leaving explicit placeholders for what only they know (role, description).
 *
 * @param context - Known candidate/session details.
 * @returns RFC 6068 mailto URL with encoded subject and body.
 */
export function buildSupportMailto(context: SupportContext): string {
  const subject = `Assessment support request - ${field(context.packageCode)}`;
  const body = [
    `Full Name: ${field(context.fullName)}`,
    `Package Code: ${field(context.packageCode)}`,
    `Applied Role: ${PLACEHOLDER}`,
    `Device/Browser: ${context.userAgent || PLACEHOLDER}`,
    `Page: ${context.pagePath || PLACEHOLDER}`,
    '',
    'What happened:',
    PLACEHOLDER,
    '',
    'Screenshots: please attach screenshots of the issue to this email.',
  ].join('\r\n');
  return `mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

/** Read the current candidate's support context from the browser. */
export function readSupportContext(): SupportContext {
  return {
    fullName: localStorage.getItem('candidateName'),
    packageCode: localStorage.getItem('candidateAccessCode'),
    userAgent: navigator.userAgent,
    pagePath: window.location.pathname,
  };
}
