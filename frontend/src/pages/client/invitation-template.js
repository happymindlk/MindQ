import { formatDeadlineTimestamp } from '../../lib/format-deadline';

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
  const deadline = formatDeadlineTimestamp(pkg?.close_time);
  return [
    'Hello,',
    '',
    `As part of your application for the ${role} role${companyName ? ` at ${companyName}` : ''}, please complete the online assessment below.`,
    '',
    `Assessment link: ${url}`,
    `Access PIN: ${pkg.access_code}`,
    `Deadline: ${deadline}`,
    '',
    'Use the email address this invitation was sent to when you sign in. The assessment is timed, so please start when you have an uninterrupted block of time.',
    '',
    'Best regards,',
    companyName ? `${companyName} Talent Team` : 'Talent Team',
  ].join('\n');
}
