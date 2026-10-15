import React, { useCallback, useMemo } from 'react';
import { Copy, KeyRound, Link2, MailPlus } from 'lucide-react';
import { useToast } from '../../components/ui/useToast';

/**
 * Plain-text invitation HR can paste into email/Slack.
 *
 * @param {{ title: string, target_role: string | null, access_code: string }} pkg
 * @param {string} url Absolute candidate portal URL.
 * @param {string} companyName
 */
function buildInvitationTemplate(pkg, url, companyName) {
  const role = pkg.target_role || pkg.title;
  return [
    'Hello,',
    '',
    `As part of your application for the ${role} role${companyName ? ` at ${companyName}` : ''}, please complete the online assessment below.`,
    '',
    `Assessment link: ${url}`,
    `Access PIN: ${pkg.access_code}`,
    '',
    'Use the email address this invitation was sent to when you sign in. The assessment is timed, so please start when you have an uninterrupted block of time.',
    '',
    'Best regards,',
    companyName ? `${companyName} Talent Team` : 'Talent Team',
  ].join('\n');
}

async function writeClipboard(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const el = document.createElement('textarea');
  el.value = text;
  el.setAttribute('readonly', '');
  el.style.cssText = 'position:fixed;opacity:0;';
  document.body.appendChild(el);
  el.select();
  const ok = document.execCommand('copy');
  el.remove();
  if (!ok) throw new Error('Clipboard unavailable');
}

const actionClass =
  'inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 focus-visible:ring-offset-2 focus-visible:ring-offset-canvas';

/** @param {{ pkg: object, companyName: string }} props */
export default function CandidateShareBanner({ pkg, companyName }) {
  const { toast } = useToast();
  const url = useMemo(
    () => `${window.location.origin}${pkg.candidate_path}`,
    [pkg.candidate_path],
  );

  const copy = useCallback(
    async (text, title) => {
      try {
        await writeClipboard(text);
        toast({ title, variant: 'success', duration: 2500 });
      } catch {
        toast({ title: 'Copy failed', description: 'Select and copy the text manually.', variant: 'error' });
      }
    },
    [toast],
  );

  return (
    <div className="flex flex-col gap-3 rounded-md border border-border bg-surface-raised/60 p-3 sm:flex-row sm:items-center sm:justify-between">
      <dl className="grid min-w-0 gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:gap-6">
        <div className="min-w-0">
          <dt className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-muted">
            <Link2 className="h-3 w-3" aria-hidden="true" />
            Candidate access URL
          </dt>
          <dd className="mt-0.5 truncate font-mono text-xs text-foreground" title={url}>
            {url}
          </dd>
        </div>
        <div>
          <dt className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-muted">
            <KeyRound className="h-3 w-3" aria-hidden="true" />
            PIN
          </dt>
          <dd className="mt-0.5 font-mono text-sm font-semibold tracking-widest text-foreground tabular-nums">
            {pkg.access_code}
          </dd>
        </div>
      </dl>
      <div className="flex shrink-0 flex-wrap gap-2">
        <button
          type="button"
          onClick={() => copy(url, 'Candidate link copied')}
          className={`${actionClass} bg-indigo-600 text-white hover:bg-indigo-700 active:bg-indigo-800`}
        >
          <Copy className="h-3.5 w-3.5" aria-hidden="true" />
          Copy Candidate Link
        </button>
        <button
          type="button"
          onClick={() => copy(buildInvitationTemplate(pkg, url, companyName), 'Invitation template copied')}
          className={`${actionClass} border border-border text-foreground hover:border-muted/40 hover:bg-surface-raised`}
        >
          <MailPlus className="h-3.5 w-3.5" aria-hidden="true" />
          Copy Invitation Template
        </button>
      </div>
    </div>
  );
}
