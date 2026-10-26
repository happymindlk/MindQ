import React, { useMemo, useState } from 'react';
import { CheckCircle2, LifeBuoy } from 'lucide-react';
import Modal from './ui/Modal';
import Button from './ui/Button';
import { API_ORIGIN } from '../lib/api-origin';
import {
  SUPPORT_EMAIL,
  buildSupportMailto,
  readSupportContext,
} from '../features/candidate-support/support-mailto';

const API_BASE = `${API_ORIGIN}/api/v1`;

const NETWORK_ERROR_MESSAGE =
  `Couldn't reach our support team. Check your connection, or email us at ${SUPPORT_EMAIL}.`;

export default function SupportModal() {
  const [open, setOpen] = useState(false);
  const [details, setDetails] = useState('');
  const [sent, setSent] = useState(false);
  const [error, setError] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const mailtoHref = useMemo(() => (open ? buildSupportMailto(readSupportContext()) : ''), [open ]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      // Device, package, and session context are attached automatically so
      // the candidate only has to describe the issue itself.
      const context = readSupportContext();
      const res = await fetch(`${API_BASE}/support/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          details: details.trim(),
          candidate_id: localStorage.getItem('candidateId') || null,
          package_code: context.packageCode,
          path: context.pagePath,
          user_agent: context.userAgent,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || 'Failed to submit support ticket');
      }
      setSent(true);
      setDetails('');
    } catch (err) {
      // A rejected fetch (offline, DNS, CORS, unreachable upstream) surfaces
      // as a raw TypeError: Failed to fetch; translate it for the candidate.
      setError(err instanceof TypeError ? NETWORK_ERROR_MESSAGE : err.message || 'Failed to submit');
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
          fixed bottom-4 right-4 z-50 flex items-center gap-2 h-10 px-3 rounded-md border-0
          bg-primary text-primary-fg text-sm font-medium shadow-none
          hover:bg-primary-hover active:bg-primary-active
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
        title="Need Help?"
        contentClassName="max-h-[90vh] overflow-y-auto"
        actions={<Button variant="ghost" onClick={() => setOpen(false)}>Close</Button>}
      >
        {sent ? (
          <div role="status" className="flex flex-col items-center gap-2 py-6 text-center">
            <CheckCircle2 className="h-10 w-10 text-success" aria-hidden="true" />
            <p className="text-sm font-medium text-foreground">Thanks! Our team will look into this.</p>
          </div>
        ) : (
          <div className="space-y-4">
            <form onSubmit={handleSubmit} className="space-y-3">
              <label htmlFor="support-details" className="sr-only">
                Describe the issue
              </label>
              <textarea
                id="support-details"
                className="
                  w-full h-32 rounded-md bg-canvas border border-border text-foreground text-sm p-3
                  placeholder:text-muted/70
                  focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:border-primary
                "
                placeholder="Briefly describe the issue you're facing..."
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
                className="w-full"
                disabled={!details.trim() || isSubmitting}
                isLoading={isSubmitting}
              >
                Send quick report
              </Button>
            </form>
            <p className="text-center text-xs text-muted">
              <a
                href={mailtoHref}
                className="text-primary-text underline-offset-2 transition-colors hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-primary"
              >
                Or email us directly at {SUPPORT_EMAIL}
              </a>
            </p>
          </div>
        )}
      </Modal>
    </>
  );
}
