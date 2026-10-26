import React, { useEffect, useId, useMemo, useRef, useState } from 'react';
import { Check, Copy, Info, Mail } from 'lucide-react';
import Modal from '../../../components/ui/Modal';
import Input from '../../../components/ui/Input';
import Button from '../../../components/ui/Button';
import { useToast } from '../../../components/ui/useToast';
import { adminApi } from '../../../lib/adminApi';
import { formatDeadlineTimestamp } from '../../../lib/format-deadline';

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@.]+$/;
const COPIED_RESET_MS = 1800;
const OTHER_VALUE = '__other__';

/**
 * Unique HR emails for a company: contact_email ∪ allowed_hr_emails.
 * Case-insensitive dedupe; preserves first-seen casing for display.
 *
 * @param {{ contact_email?: string | null, allowed_hr_emails?: string[] } | null} corporate
 * @returns {string[]}
 */
function buildHrEmails(corporate) {
  const seen = new Set();
  const emails = [];
  for (const raw of [corporate?.contact_email, ...(corporate?.allowed_hr_emails || [])]) {
    if (!raw || typeof raw !== 'string') continue;
    const trimmed = raw.trim();
    if (!trimmed) continue;
    const key = trimmed.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    emails.push(trimmed);
  }
  return emails;
}

/**
 * Read-only preview block with a copy-to-clipboard icon button.
 */
function PreviewBox({ title, rows, copyLabel, copyText, copied, onCopy }) {
  return (
    <div className="rounded-md border border-neutral-800 bg-neutral-900 px-4 py-3">
      <div className="flex items-center justify-between gap-2 mb-2">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-neutral-400">{title}</p>
        <button
          type="button"
          onClick={() => onCopy(copyText)}
          aria-label={copyLabel}
          title={copyLabel}
          className="p-1.5 rounded-md text-neutral-400 transition-colors duration-150 hover:text-neutral-100 hover:bg-neutral-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
        >
          {copied ? (
            <Check className="w-3.5 h-3.5 text-emerald-400" aria-hidden="true" />
          ) : (
            <Copy className="w-3.5 h-3.5" aria-hidden="true" />
          )}
        </button>
      </div>
      <dl className="space-y-2">
        {rows.map((row) => (
          <div key={row.label}>
            <dt className="text-xs text-neutral-400">{row.label}</dt>
            <dd
              className={`mt-0.5 font-mono break-all text-neutral-100 ${
                row.emphasis ? 'text-base tracking-wider text-blue-300' : 'text-xs'
              }`}
            >
              {row.value}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/**
 * Share a published package: preview + copy links, and email them to the client HR.
 *
 * @param {object} props
 * @param {boolean} props.isOpen
 * @param {import('./use-corporate-packages').CorporatePackage | null} props.pkg
 * @param {{ name: string, contact_email: string | null, allowed_hr_emails?: string[] } | null} props.corporate
 * @param {() => void} props.onClose
 */
export default function SharePackageModal({ isOpen, pkg, corporate, onClose }) {
  const { toast } = useToast();
  const formId = useId();
  const selectId = useId();
  const customInputRef = useRef(null);
  const [recipient, setRecipient] = useState('');
  const [selectValue, setSelectValue] = useState(OTHER_VALUE);
  const [fieldError, setFieldError] = useState(null);
  const [submitError, setSubmitError] = useState(null);
  const [isSending, setIsSending] = useState(false);
  const [copiedKey, setCopiedKey] = useState(null);
  const copiedTimerRef = useRef(null);

  const hrEmails = useMemo(() => buildHrEmails(corporate), [corporate]);
  const isOther = selectValue === OTHER_VALUE;

  useEffect(() => {
    if (!isOpen) return;
    const defaultEmail = corporate?.contact_email?.trim() || hrEmails[0] || '';
    if (defaultEmail) {
      setSelectValue(defaultEmail);
      setRecipient(defaultEmail);
    } else {
      setSelectValue(OTHER_VALUE);
      setRecipient('');
    }
    setFieldError(null);
    setSubmitError(null);
    setCopiedKey(null);
  }, [isOpen, corporate?.contact_email, hrEmails]);

  useEffect(() => () => clearTimeout(copiedTimerRef.current), []);

  useEffect(() => {
    if (!isOpen || !isOther) return;
    customInputRef.current?.focus();
  }, [isOpen, isOther]);

  const frontendOrigin = (
    import.meta.env.VITE_FRONTEND_URL || window.location.origin
  ).replace(/\/+$/, '');
  const accessCode = pkg?.access_code ?? '';
  const candidateLink = accessCode
    ? `${frontendOrigin}/portal?code=${encodeURIComponent(accessCode)}`
    : (pkg?.candidate_link ?? '');
  const hrLink = `${frontendOrigin}/client/login`;
  const candidateInvite = [
    `Assessment: ${pkg?.title ?? ''}`,
    `Test link: ${candidateLink}`,
    `PIN: ${accessCode}`,
    `Deadline: ${formatDeadlineTimestamp(pkg?.close_time)}`,
  ].join('\n');
  // The HR link itself carries no tenant binding: whoever signs in lands in
  // the company their own HR membership + whitelist point at. Name that
  // company here so a mismatch is visible before sending.
  const allowedSet = useMemo(() => {
    const set = new Set(hrEmails.map((email) => email.toLowerCase()));
    return set;
  }, [hrEmails]);
  const recipientWhitelisted =
    !recipient.trim() ||
    allowedSet.size === 0 ||
    allowedSet.has(recipient.trim().toLowerCase());

  const copy = async (key, text) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedKey(key);
      clearTimeout(copiedTimerRef.current);
      copiedTimerRef.current = setTimeout(() => setCopiedKey(null), COPIED_RESET_MS);
    } catch {
      toast({
        variant: 'error',
        title: 'Copy failed',
        description: 'Clipboard access was blocked. Select the text and copy it manually.',
      });
    }
  };

  const handleClose = () => {
    if (!isSending) onClose();
  };

  const handleSelectChange = (event) => {
    const value = event.target.value;
    setSelectValue(value);
    setFieldError(null);
    if (value === OTHER_VALUE) {
      setRecipient('');
      return;
    }
    setRecipient(value);
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    const trimmed = recipient.trim();
    if (!trimmed) {
      setFieldError('Enter a recipient email.');
      return;
    }
    if (!EMAIL_PATTERN.test(trimmed)) {
      setFieldError('Enter a valid email address.');
      return;
    }
    setFieldError(null);
    setSubmitError(null);
    setIsSending(true);
    try {
      const result = await adminApi.sharePackage(pkg.id, { recipientEmail: trimmed });
      toast({ variant: 'success', title: 'Invite sent', description: `Invite sent to ${result.sent_to}` });
      onClose();
    } catch (err) {
      const message = err.message || 'Failed to send invite email';
      setSubmitError(message);
      toast({ variant: 'error', title: 'Send failed', description: message });
    } finally {
      setIsSending(false);
    }
  };

  const selectClassName = `
    block w-full h-9 rounded-md bg-canvas border text-foreground text-sm
    pl-3 pr-3
    focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:border-primary
    transition-colors duration-150 ease-out
    border-slate-200 dark:border-neutral-800 hover:border-neutral-400 dark:hover:border-neutral-700
    disabled:opacity-50
  `;

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title={pkg ? `Share ${pkg.title}` : 'Share assessment'}
      actions={
        <>
          <Button type="button" variant="secondary" size="sm" onClick={handleClose} disabled={isSending}>
            Cancel
          </Button>
          <Button type="submit" form={formId} variant="accent" size="sm" isLoading={isSending} disabled={!pkg}>
            <Mail className="w-3.5 h-3.5" aria-hidden="true" />
            Send Invite Email
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={handleSubmit} noValidate className="space-y-4">
        <div className="w-full">
          <label htmlFor={selectId} className="metric-label mb-1.5 block">
            Recipient email
          </label>
          <select
            id={selectId}
            value={selectValue}
            onChange={handleSelectChange}
            disabled={isSending}
            className={selectClassName}
            aria-label="Recipient email"
          >
            {hrEmails.map((email) => (
              <option key={email.toLowerCase()} value={email}>
                {email}
              </option>
            ))}
            <option value={OTHER_VALUE}>Other / Add custom email...</option>
          </select>
        </div>

        {isOther && (
          <Input
            ref={customInputRef}
            label="Custom email"
            type="email"
            icon={Mail}
            value={recipient}
            onChange={(event) => setRecipient(event.target.value)}
            placeholder="hr@company.com"
            error={fieldError}
            disabled={isSending}
            autoComplete="off"
          />
        )}

        {!isOther && fieldError && (
          <p className="text-xs text-danger" role="alert">
            {fieldError}
          </p>
        )}

        <PreviewBox
          title="Candidate access"
          rows={[
            { label: 'Test link', value: candidateLink },
            { label: 'PIN', value: accessCode, emphasis: true },
          ]}
          copyLabel="Copy Candidate Invite"
          copyText={candidateInvite}
          copied={copiedKey === 'candidate'}
          onCopy={(text) => copy('candidate', text)}
        />
        <PreviewBox
          title={corporate?.name ? `HR portal access — ${corporate.name}` : 'HR portal access'}
          rows={[{ label: 'Login link', value: hrLink }]}
          copyLabel="Copy HR Link"
          copyText={hrLink}
          copied={copiedKey === 'hr'}
          onCopy={(text) => copy('hr', text)}
        />
        {recipient.trim() && !recipientWhitelisted && (
          <p className="flex items-start gap-1.5 text-xs text-amber-400" role="alert">
            <Info className="w-3.5 h-3.5 shrink-0 mt-px" aria-hidden="true" />
            {recipient.trim()} is not on {corporate?.name ?? 'this company'}&apos;s allowed HR
            emails list, so they will not be able to sign in. Add them under Manage Corporates
            first.
          </p>
        )}

        <p className="flex items-start gap-1.5 text-xs text-neutral-400">
          <Info className="w-3.5 h-3.5 shrink-0 mt-px" aria-hidden="true" />
          Sending enables open enrollment: anyone with this code can start the assessment.
        </p>

        {submitError && (
          <p className="text-xs text-danger" role="alert">
            {submitError}
          </p>
        )}
      </form>
    </Modal>
  );
}
