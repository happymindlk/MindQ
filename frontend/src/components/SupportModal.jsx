import React, { useMemo, useState } from 'react';
import { Briefcase, Camera, Hash, LifeBuoy, Mail, MonitorSmartphone, User } from 'lucide-react';
import Modal from './ui/Modal';
import Button from './ui/Button';
import {
  SUPPORT_EMAIL,
  buildSupportMailto,
  readSupportContext,
} from '../features/candidate-support/support-mailto';

const API_BASE = `${import.meta.env.VITE_API_URL || ''}/api/v1`;

const CHECKLIST = [
  { icon: User, label: 'Full Name', hint: 'As entered when you signed in.' },
  { icon: Hash, label: 'Package Code', hint: 'The access code from your invitation (e.g. HM-ABCDEF-1).' },
  { icon: Briefcase, label: 'Applied Role', hint: 'The position you are being assessed for.' },
  { icon: MonitorSmartphone, label: 'Device / Browser info', hint: 'e.g. Windows laptop, Chrome 128 or iPhone, Safari.' },
  { icon: Camera, label: 'Screenshots of the issue', hint: 'Attach them to your email, including any error message.' },
];

export default function SupportModal() {
  const [open, setOpen] = useState(false);
  const [details, setDetails] = useState('');
  const [sent, setSent] = useState(false);
  const [error, setError] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const mailtoHref = useMemo(() => (open ? buildSupportMailto(readSupportContext()) : ''), [open]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      const res = await fetch(`${API_BASE}/support/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          details: details.trim(),
          candidate_id: localStorage.getItem('candidateId') || null,
          path: window.location.pathname,
          user_agent: navigator.userAgent,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || 'Failed to submit support ticket');
      }
      setSent(true);
      setDetails('');
    } catch (err) {
      setError(err.message || 'Failed to submit');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => {
          setOpen(true);
          setSent(false);
          setError(null);
        }}
        className="
          fixed bottom-4 right-4 z-50 flex items-center gap-2 h-10 px-3 rounded-md
          bg-primary text-primary-fg text-sm font-medium
          hover:bg-primary-hover
          focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-canvas
        "
        aria-label="Technical Support"
      >
        <LifeBuoy className="w-4 h-4" aria-hidden="true" />
        <span className="hidden sm:inline">Technical Support</span>
      </button>

      <Modal
        isOpen={open}
        onClose={() => setOpen(false)}
        title="Technical Support"
        contentClassName="max-h-[90vh] overflow-y-auto"
        actions={<Button variant="ghost" onClick={() => setOpen(false)}>Close</Button>}
      >
        <div className="space-y-5">
          <section aria-labelledby="support-email-heading" className="space-y-3">
            <h3 id="support-email-heading" className="text-sm font-semibold text-foreground">
              Email our support team
            </h3>
            <p className="leading-relaxed">
              So we can find your assessment and fix the problem quickly, please include:
            </p>
            <ul className="space-y-2.5">
              {CHECKLIST.map(({ icon: Icon, label, hint }) => (
                <li key={label} className="flex gap-3">
                  <Icon className="mt-0.5 h-4 w-4 shrink-0 text-primary-text" aria-hidden="true" />
                  <span>
                    <span className="font-medium text-foreground">{label}</span>
                    <span className="block text-xs text-muted">{hint}</span>
                  </span>
                </li>
              ))}
            </ul>
            <a
              href={mailtoHref}
              className="flex h-10 w-full items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-fg transition-colors hover:bg-primary-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
            >
              <Mail className="h-4 w-4" aria-hidden="true" />
              Email {SUPPORT_EMAIL}
            </a>
            <p className="text-xs text-muted">
              The email opens pre-filled with the details we already know. Add your role, describe the
              issue, and attach screenshots. No mail app? Write to{' '}
              <a href={`mailto:${SUPPORT_EMAIL}`} className="font-medium text-primary-text underline underline-offset-2">
                {SUPPORT_EMAIL}
              </a>{' '}
              directly.
            </p>
          </section>

          <section aria-labelledby="support-quick-heading" className="space-y-3 border-t border-border pt-4">
            <h3 id="support-quick-heading" className="text-sm font-semibold text-foreground">
              Or send a quick report without leaving this page
            </h3>
            {sent ? (
              <p role="status" className="rounded-md border border-success/30 bg-success/10 px-3 py-2 text-sm text-success">
                Report saved. Your page and browser details were attached. Keep this tab open; the timer
                keeps running.
              </p>
            ) : (
              <form onSubmit={handleSubmit} className="space-y-3">
                <label htmlFor="support-details" className="sr-only">
                  Describe the issue
                </label>
                <textarea
                  id="support-details"
                  className="
                    w-full h-24 rounded-md bg-canvas border border-border text-foreground text-sm p-3
                    placeholder:text-muted/70
                    focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:border-primary
                  "
                  placeholder="e.g. Next button did nothing after question 4…"
                  value={details}
                  onChange={(e) => setDetails(e.target.value)}
                />
                {error && (
                  <p className="text-xs text-danger" role="alert">
                    {error}
                  </p>
                )}
                <Button
                  type="submit"
                  variant="secondary"
                  className="w-full"
                  disabled={!details.trim() || isSubmitting}
                  isLoading={isSubmitting}
                >
                  Send quick report
                </Button>
              </form>
            )}
          </section>
        </div>
      </Modal>
    </>
  );
}
