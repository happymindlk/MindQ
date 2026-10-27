import React, { useCallback } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import Card from '../../components/ui/Card';
import BrandLogo from '../../components/BrandLogo';
import { PreviewRunner } from '../../features/assessment-runner/preview-runner';
import { PREVIEW_ACCESS_CODE } from '../../features/assessment-builder/lib/preview-protocol';
import {
  OTP_MAX_LENGTH,
  OTP_MIN_LENGTH,
  useCandidateOtpLogin,
} from '../../features/candidate-auth/use-candidate-otp-login';

const FIELD_INPUT =
  'w-full pl-10 pr-4 py-2.5 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg text-sm text-slate-900 dark:text-slate-100 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-[#7048E2]/20 focus:border-[#7048E2] transition-colors disabled:opacity-60';

const FIELD_LABEL =
  'block text-xs font-semibold uppercase tracking-wider text-slate-600 dark:text-slate-400 mb-1.5';

const CTA_PRIMARY =
  'w-full bg-[#7048E2] hover:bg-[#5e3cc4] active:bg-[#4f32a6] text-white font-medium py-2.5 rounded-lg transition-all shadow-sm flex items-center justify-center';

function IconKey({ className = 'w-4 h-4' }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" />
    </svg>
  );
}

function IconUser({ className = 'w-4 h-4' }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  );
}

function IconMail({ className = 'w-4 h-4' }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect width="20" height="16" x="2" y="4" rx="2" />
      <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
    </svg>
  );
}

function IconArrowRight({ className = 'w-4 h-4' }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5 12h14" />
      <path d="m12 5 7 7-7 7" />
    </svg>
  );
}

function IconArrowLeft({ className = 'w-4 h-4' }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M19 12H5" />
      <path d="m12 19-7-7 7-7" />
    </svg>
  );
}

function IconRefresh({ className = 'w-4 h-4' }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8" />
      <path d="M21 3v5h-5" />
    </svg>
  );
}

function IconSpinner({ className = 'w-4 h-4' }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
    </svg>
  );
}

function Field({
  id,
  label,
  icon,
  className = '',
  ...props
}) {
  return (
    <div className="w-full">
      <label htmlFor={id} className={FIELD_LABEL}>
        {label}
      </label>
      <div className="relative">
        <span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400">
          {icon}
        </span>
        <input id={id} className={`${FIELD_INPUT} ${className}`} {...props} />
      </div>
    </div>
  );
}

export default function Login() {
  const [searchParams] = useSearchParams();
  if (searchParams.get('code') === PREVIEW_ACCESS_CODE) {
    return <PreviewRunner />;
  }
  return <CandidateLogin initialAccessCode={(searchParams.get('code') || '').trim()} />;
}

function StepIndicator({ step }) {
  const detailsActive = step === 'details';
  const codeActive = step === 'code';
  return (
    <ol className="mb-5 flex items-center gap-3" aria-label="Sign-in progress">
      <li
        className="flex items-center gap-2"
        aria-current={detailsActive ? 'step' : undefined}
      >
        <span
          className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold ${
            detailsActive
              ? 'bg-[#7048E2] text-white'
              : 'bg-slate-100 text-slate-400 dark:bg-slate-800'
          }`}
        >
          1
        </span>
        <span
          className={`text-xs ${
            detailsActive
              ? 'font-medium text-slate-900 dark:text-slate-100'
              : 'text-slate-400'
          }`}
        >
          Your Details
        </span>
      </li>
      <li aria-hidden="true" className="h-[1px] w-8 bg-slate-200 dark:bg-slate-700" />
      <li
        className="flex items-center gap-2"
        aria-current={codeActive ? 'step' : undefined}
      >
        <span
          className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold ${
            codeActive
              ? 'bg-[#7048E2] text-white'
              : 'bg-slate-100 text-slate-400 dark:bg-slate-800'
          }`}
        >
          2
        </span>
        <span
          className={`text-xs ${
            codeActive
              ? 'font-medium text-slate-900 dark:text-slate-100'
              : 'text-slate-400'
          }`}
        >
          Verification
        </span>
      </li>
    </ol>
  );
}

function FormError({ message }) {
  if (!message) return null;
  return (
    <p role="alert" className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
      {message}
    </p>
  );
}

function CandidateLogin({ initialAccessCode }) {
  const navigate = useNavigate();
  const onAuthenticated = useCallback(() => navigate('/portal/guidelines'), [navigate]);
  const login = useCandidateOtpLogin(initialAccessCode, onAuthenticated);
  const { step, identity, loading } = login;

  const submitDetails = (e) => {
    e.preventDefault();
    void login.sendCode();
  };

  const submitCode = (e) => {
    e.preventDefault();
    void login.verifyCode();
  };

  return (
    <div className="flex-1 flex flex-col justify-center items-center w-full py-8">
      <div className="w-full max-w-md">
        <BrandLogo collapsed={false} className="h-10 w-auto mx-auto mb-6 object-contain" />
        <div className="mb-6">
          <h1 className="font-display text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
            {step === 'details' ? 'Welcome to Your Assessment' : 'Check your inbox'}
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-slate-500 dark:text-slate-400">
            {step === 'details'
              ? 'Before you begin, please enter your details to access your assessment. Provide your first and last name as they appear on your application, along with your email address.'
              : 'Enter the code we emailed you to continue to your assessment.'}
          </p>
        </div>

        <Card variant="elevated" padding="p-4 sm:p-6">
          <StepIndicator step={step} />

          {step === 'details' ? (
            <form onSubmit={submitDetails} className="space-y-4" noValidate>
              <Field
                id="candidate-access-code"
                label="Access Code"
                icon={<IconKey />}
                placeholder="e.g. HM-ABCDEF-1"
                value={identity.accessCode}
                onChange={(e) => login.updateField('accessCode', e.target.value)}
                className="tabular-data"
                autoComplete="off"
                disabled={loading}
                required
              />
              <Field
                id="candidate-first-name"
                label="First Name"
                icon={<IconUser />}
                placeholder="What should we call you?"
                value={identity.firstName}
                onChange={(e) => login.updateField('firstName', e.target.value)}
                autoComplete="given-name"
                maxLength={100}
                disabled={loading}
                required
              />
              <Field
                id="candidate-last-name"
                label="Last Name"
                icon={<IconUser />}
                placeholder="Last name on your application"
                value={identity.lastName}
                onChange={(e) => login.updateField('lastName', e.target.value)}
                autoComplete="family-name"
                maxLength={100}
                disabled={loading}
                required
              />
              <Field
                id="candidate-email"
                label="Email"
                type="email"
                icon={<IconMail />}
                placeholder="you@example.com"
                value={identity.email}
                onChange={(e) => login.updateField('email', e.target.value)}
                autoComplete="email"
                inputMode="email"
                disabled={loading}
                required
              />
              <p className="rounded-lg border border-slate-200/80 bg-slate-50 p-3.5 text-xs leading-normal text-slate-500 dark:border-slate-800 dark:bg-slate-900/60 dark:text-slate-400">
                <span className="font-semibold text-slate-700 dark:text-slate-300">Notice:</span> Assessment results are
                generated based on your responses and should be interpreted within the context of the
                organization&apos;s overall selection process. MindQ does not guarantee or determine any employment
                outcome based on the results of this assessment. By proceeding, you acknowledge that you understand the
                purpose of the assessment and agree to complete it to the best of your ability.
              </p>
              <FormError message={login.error} />
              <button
                type="submit"
                className={`${CTA_PRIMARY} disabled:cursor-not-allowed disabled:opacity-50`}
                disabled={loading || !login.canSend}
              >
                {loading && <IconSpinner className="mr-2 h-4 w-4" />}
                Send verification code
                {!loading && <IconArrowRight className="ml-2 h-4 w-4" />}
              </button>
            </form>
          ) : (
            <form onSubmit={submitCode} className="space-y-4" noValidate>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                Code sent to <span className="break-all font-medium text-slate-900 dark:text-slate-100">{identity.email.trim()}</span>
              </p>
              <div>
                <label htmlFor="candidate-otp" className={FIELD_LABEL}>
                  One-time code
                </label>
                <input
                  id="candidate-otp"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  autoFocus
                  placeholder="000000"
                  maxLength={OTP_MAX_LENGTH}
                  value={login.code}
                  onChange={(e) => login.setCode(e.target.value)}
                  disabled={loading}
                  aria-describedby="candidate-otp-hint"
                  className="block h-12 w-full rounded-lg border border-slate-200 bg-white px-3 text-center font-mono text-xl tracking-[0.4em] tabular-nums text-slate-900 placeholder:text-slate-400 transition-colors focus:border-[#7048E2] focus:outline-none focus:ring-2 focus:ring-[#7048E2]/20 disabled:opacity-60 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-100"
                />
                <p id="candidate-otp-hint" className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                  {OTP_MIN_LENGTH}-digit code. Check spam if it does not arrive within a minute.
                </p>
              </div>
              <FormError message={login.error} />
              <button
                type="submit"
                className={`${CTA_PRIMARY} disabled:cursor-not-allowed disabled:opacity-50`}
                disabled={loading || !login.canVerify}
              >
                {loading && <IconSpinner className="mr-2 h-4 w-4" />}
                Verify and continue
                {!loading && <IconArrowRight className="ml-2 h-4 w-4" />}
              </button>
              <div className="flex items-center justify-between gap-2 pt-1">
                <button
                  type="button"
                  onClick={login.editDetails}
                  disabled={loading}
                  className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs text-slate-500 transition-colors hover:text-slate-900 focus-visible:ring-2 focus-visible:ring-[#7048E2] disabled:opacity-50 dark:text-slate-400 dark:hover:text-slate-100"
                >
                  <IconArrowLeft className="h-3.5 w-3.5" />
                  Edit details
                </button>
                <button
                  type="button"
                  onClick={() => void login.resendCode()}
                  disabled={loading || login.cooldown > 0}
                  className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs text-[#5e3cc4] transition-colors hover:underline focus-visible:ring-2 focus-visible:ring-[#7048E2] disabled:cursor-not-allowed disabled:text-slate-400 disabled:no-underline"
                >
                  <IconRefresh className="h-3.5 w-3.5" />
                  {login.cooldown > 0 ? `Resend in ${login.cooldown}s` : 'Resend code'}
                </button>
              </div>
            </form>
          )}
        </Card>
        <p className="mt-4 text-center text-xs leading-relaxed text-slate-500 dark:text-slate-400">
          If you experience any technical difficulties while accessing or completing the assessment, please click
          &lsquo;Technical Support&rsquo; to contact our technical support team.
        </p>
      </div>
    </div>
  );
}
