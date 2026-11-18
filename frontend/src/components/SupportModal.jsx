import React, { useEffect, useMemo, useState } from 'react';
import Modal from './ui/Modal';
import Button from './ui/Button';
import { API_ORIGIN } from '../lib/api-origin';
import {
  getDeviceContext,
  readAccessCode,
  readLoginDraftEmail,
  readLoginDraftName,
} from '../lib/device';
import {
  SUPPORT_EMAIL,
  buildSupportMailto,
  readSupportContext,
} from '../features/candidate-support/support-mailto';

const API_BASE = `${API_ORIGIN}/api/v1`;

const NETWORK_ERROR_MESSAGE =
  `Couldn't reach our support team. Check your connection, or email us at ${SUPPORT_EMAIL}.`;

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
/** Digits only; E.164-ish length after stripping formatting. */
const PHONE_DIGITS_MIN = 7;
const PHONE_DIGITS_MAX = 15;

function LifeBuoyIcon({ className }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="10" />
      <circle cx="12" cy="12" r="4" />
      <path d="m4.93 4.93 4.24 4.24" />
      <path d="m14.83 9.17 4.24-4.24" />
      <path d="m14.83 14.83 4.24 4.24" />
      <path d="m9.17 14.83-4.24 4.24" />
    </svg>
  );
}

function CheckIcon({ className }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
      <path d="m9 11 3 3L22 4" />
    </svg>
  );
}

function digitCount(value) {
  return (value || '').replace(/\D/g, '').length;
}

function validateEmail(value) {
  const trimmed = (value || '').trim();
  if (!trimmed) return 'Email address is required.';
  if (!EMAIL_PATTERN.test(trimmed)) return 'Enter a valid email address.';
  return null;
}

function validateContactNumber(value) {
  const trimmed = (value || '').trim();
  if (!trimmed) return 'Contact number is required.';
  const digits = digitCount(trimmed);
  if (digits < PHONE_DIGITS_MIN || digits > PHONE_DIGITS_MAX) {
    return `Enter a valid phone number (${PHONE_DIGITS_MIN}–${PHONE_DIGITS_MAX} digits).`;
  }
  if (!/^[+\d][\d\s().-]*$/.test(trimmed)) {
    return 'Enter a valid phone number.';
  }
  return null;
}

function validateDetails(value) {
  if (!(value || '').trim()) return 'Please describe the issue.';
  return null;
}

const fieldClassName = `
  w-full rounded-md bg-canvas border border-border text-foreground text-sm p-3
  placeholder:text-muted/70
  focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:border-primary
`;

export default function SupportModal() {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState('');
  const [contactNumber, setContactNumber] = useState('');
  const [details, setDetails] = useState('');
  const [touched, setTouched] = useState({ email: false, contactNumber: false, details: false });
  const [sent, setSent] = useState(false);
  const [error, setError] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const mailtoHref = useMemo(() => (open ? buildSupportMailto(readSupportContext()) : ''), [open]);

  useEffect(() => {
    if (!open) return;
    const draftEmail = readLoginDraftEmail();
    if (draftEmail) {
      setEmail((prev) => prev || draftEmail);
    }
  }, [open]);

  const emailError = validateEmail(email);
  const contactError = validateContactNumber(contactNumber);
  const detailsError = validateDetails(details);
  const formValid = !emailError && !contactError && !detailsError;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setTouched({ email: true, contactNumber: true, details: true });
    if (!formValid) return;
    setError(null);
    setIsSubmitting(true);
    try {
      const device = getDeviceContext();
      const accessCode = readAccessCode();
      const enteredName = readLoginDraftName() || null;
      const res = await fetch(`${API_BASE}/support/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: email.trim(),
          contact_number: contactNumber.trim(),
          details: details.trim(),
          description: details.trim(),
          candidate_id: localStorage.getItem('candidateId') || null,
          access_code: accessCode || null,
          package_code: accessCode || null,
          entered_name: enteredName,
          device_id: device.device_id,
          browser: device.browser,
          page_url: device.page_url,
          path: typeof window !== 'undefined' ? window.location.pathname : null,
          user_agent: device.user_agent,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || 'Failed to submit support ticket');
      }
      setSent(true);
      setDetails('');
      setContactNumber('');
      setTouched({ email: false, contactNumber: false, details: false });
    } catch (err) {
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
          const draftEmail = readLoginDraftEmail();
          if (draftEmail) setEmail(draftEmail);
        }}
        className="
          fixed bottom-4 right-4 z-50 flex items-center gap-2 h-10 px-3 rounded-md
          border border-primary/20 bg-primary text-primary-fg text-sm font-medium
          shadow-md shadow-primary/20
          hover:bg-primary-hover active:bg-primary-active
          focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-canvas
          dark:border-primary/40 dark:shadow-black/40
          transition-colors duration-150
        "
        aria-label="Technical Support"
      >
        <LifeBuoyIcon className="w-4 h-4" />
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
            <CheckIcon className="h-10 w-10 text-success" />
            <p className="text-sm font-medium text-foreground">Thanks! Our team will look into this.</p>
          </div>
        ) : (
          <div className="space-y-4">
            <form onSubmit={handleSubmit} className="space-y-3" noValidate>
              <div className="space-y-1">
                <label htmlFor="support-email" className="block text-xs font-medium text-foreground">
                  Email Address
                </label>
                <input
                  id="support-email"
                  type="email"
                  autoComplete="email"
                  inputMode="email"
                  required
                  placeholder="you@example.com"
                  className={fieldClassName}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  onBlur={() => setTouched((t) => ({ ...t, email: true }))}
                  aria-invalid={touched.email && !!emailError}
                  aria-describedby={touched.email && emailError ? 'support-email-error' : undefined}
                />
                {touched.email && emailError && (
                  <p id="support-email-error" className="text-xs text-danger" role="alert">
                    {emailError}
                  </p>
                )}
              </div>

              <div className="space-y-1">
                <label htmlFor="support-contact" className="block text-xs font-medium text-foreground">
                  Contact Number
                </label>
                <input
                  id="support-contact"
                  type="tel"
                  autoComplete="tel"
                  inputMode="tel"
                  required
                  placeholder="+94 77 123 4567"
                  className={fieldClassName}
                  value={contactNumber}
                  onChange={(e) => setContactNumber(e.target.value)}
                  onBlur={() => setTouched((t) => ({ ...t, contactNumber: true }))}
                  aria-invalid={touched.contactNumber && !!contactError}
                  aria-describedby={
                    touched.contactNumber && contactError ? 'support-contact-error' : undefined
                  }
                />
                {touched.contactNumber && contactError && (
                  <p id="support-contact-error" className="text-xs text-danger" role="alert">
                    {contactError}
                  </p>
                )}
              </div>

              <div className="space-y-1">
                <label htmlFor="support-details" className="block text-xs font-medium text-foreground">
                  Describe the issue
                </label>
                <textarea
                  id="support-details"
                  className={`${fieldClassName} h-32`}
                  placeholder="Briefly describe the issue you're facing..."
                  value={details}
                  onChange={(e) => setDetails(e.target.value)}
                  onBlur={() => setTouched((t) => ({ ...t, details: true }))}
                  aria-invalid={touched.details && !!detailsError}
                  aria-describedby={touched.details && detailsError ? 'support-details-error' : undefined}
                />
                {touched.details && detailsError && (
                  <p id="support-details-error" className="text-xs text-danger" role="alert">
                    {detailsError}
                  </p>
                )}
              </div>

              {error && (
                <p className="text-xs text-danger" role="alert">
                  {error}
                </p>
              )}
              <Button
                type="submit"
                className="w-full"
                disabled={!formValid || isSubmitting}
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
