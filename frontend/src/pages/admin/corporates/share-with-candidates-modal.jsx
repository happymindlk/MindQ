import React, { useEffect, useId, useState } from 'react';
import { Mail } from 'lucide-react';
import Modal from '../../../components/ui/Modal';
import Button from '../../../components/ui/Button';
import { useToast } from '../../../components/ui/useToast';
import { adminApi } from '../../../lib/adminApi';
import { friendlyErrorMessage } from '../../../lib/friendly-error';

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@.]+$/;
const MAX_EMAILS = 100;

/**
 * Parse a comma-separated email blob into unique, trimmed addresses.
 *
 * @param {string} raw
 * @returns {{ emails: string[], invalid: string[] }}
 */
export function parseCandidateEmails(raw) {
  const seen = new Set();
  const emails = [];
  const invalid = [];
  for (const part of String(raw || '').split(',')) {
    const trimmed = part.trim();
    if (!trimmed) continue;
    if (!EMAIL_PATTERN.test(trimmed)) {
      invalid.push(trimmed);
      continue;
    }
    const key = trimmed.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    emails.push(trimmed);
  }
  return { emails, invalid };
}

/**
 * Bulk-invite candidates to a published package via comma-separated emails.
 *
 * @param {object} props
 * @param {boolean} props.isOpen
 * @param {import('./use-corporate-packages').CorporatePackage | null} props.pkg
 * @param {() => void} props.onClose
 * @param {() => void} [props.onInvited]
 */
export default function ShareWithCandidatesModal({ isOpen, pkg, onClose, onInvited }) {
  const { toast } = useToast();
  const formId = useId();
  const textareaId = useId();
  const [rawEmails, setRawEmails] = useState('');
  const [fieldError, setFieldError] = useState(null);
  const [isSending, setIsSending] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setRawEmails('');
    setFieldError(null);
    setIsSending(false);
  }, [isOpen, pkg?.id]);

  const handleClose = () => {
    if (!isSending) onClose();
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!pkg?.id) return;

    const { emails, invalid } = parseCandidateEmails(rawEmails);
    if (invalid.length) {
      setFieldError(`Invalid email${invalid.length === 1 ? '' : 's'}: ${invalid.slice(0, 3).join(', ')}`);
      return;
    }
    if (!emails.length) {
      setFieldError('Paste at least one candidate email address.');
      return;
    }
    if (emails.length > MAX_EMAILS) {
      setFieldError(`Limit is ${MAX_EMAILS} emails per invite.`);
      return;
    }

    setFieldError(null);
    setIsSending(true);
    try {
      const result = await adminApi.bulkInviteCandidates(pkg.id, emails);
      const invited = result?.invited_count ?? 0;
      const skipped = result?.skipped_count ?? 0;
      const errors = result?.error_count ?? 0;
      toast({
        variant: invited > 0 || skipped > 0 ? 'success' : 'error',
        title: 'Candidate invites queued',
        description: `${invited} invited, ${skipped} skipped${errors ? `, ${errors} failed` : ''}.`,
      });
      onInvited?.();
      onClose();
    } catch (err) {
      const message = friendlyErrorMessage(err, 'Failed to send candidate invites');
      setFieldError(message);
      toast({ variant: 'error', title: 'Invite failed', description: message });
    } finally {
      setIsSending(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title={pkg ? `Share with Candidates — ${pkg.title}` : 'Share with Candidates'}
      actions={
        <>
          <Button type="button" variant="secondary" size="sm" onClick={handleClose} disabled={isSending}>
            Cancel
          </Button>
          <Button type="submit" form={formId} variant="accent" size="sm" isLoading={isSending} disabled={!pkg}>
            <Mail className="w-3.5 h-3.5" aria-hidden="true" />
            Send Invites
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={handleSubmit} noValidate className="space-y-3">
        <div>
          <label htmlFor={textareaId} className="metric-label mb-1.5 block">
            Candidate emails
          </label>
          <textarea
            id={textareaId}
            value={rawEmails}
            onChange={(event) => {
              setRawEmails(event.target.value);
              setFieldError(null);
            }}
            disabled={isSending}
            rows={6}
            placeholder="alex@company.com, sam@company.com, jordan@company.com"
            className="block w-full rounded-md border border-slate-200 bg-canvas px-3 py-2 text-sm text-foreground placeholder:text-muted focus:outline-none focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/50 disabled:opacity-50 dark:border-neutral-800"
            aria-invalid={Boolean(fieldError)}
            aria-describedby={fieldError ? `${textareaId}-error` : undefined}
          />
          <p className="mt-1.5 text-xs text-muted">
            Paste comma-separated emails. Each new address gets a unique PIN and invite email.
          </p>
        </div>
        {fieldError && (
          <p id={`${textareaId}-error`} role="alert" className="text-xs text-danger">
            {fieldError}
          </p>
        )}
      </form>
    </Modal>
  );
}
