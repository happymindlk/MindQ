import { formatDeadlineTimestamp } from '../../lib/format-deadline';
import { formatPackageLabel } from '../../lib/format-package-label';

/**
 * Plain-text invitation HR can paste into email/Slack.
 *
 * @param {{ title: string, target_role: string | null, access_code: string, close_time?: string | null }} pkg
 * @param {string} url Absolute candidate portal URL.
 * @param {string} companyName
 * @returns {string}
 */
export function buildInvitationTemplate(pkg, url, companyName) {
  const role = pkg.target_role || pkg.title;
  const packageLabel = formatPackageLabel(pkg.title);
  const deadline = formatDeadlineTimestamp(pkg?.close_time);
  const company = (companyName || '').trim();
  return [
    'Hello,',
    '',
    `As part of your application for the ${role} role${company ? ` at ${company}` : ''}, please complete the ${packageLabel} below.`,
    '',
    `Assessment link: ${url}`,
    `Access PIN: ${pkg.access_code}`,
    `Deadline: ${deadline}`,
    '',
    'Use the email address this invitation was sent to when you sign in. The assessment is timed, so please start when you have an uninterrupted block of time.',
    '',
    'Best regards,',
    company ? `${company} Talent Team` : 'The MindQ Team',
  ].join('\n');
}
