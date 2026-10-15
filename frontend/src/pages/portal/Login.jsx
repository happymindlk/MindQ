import React, { useCallback } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowLeft, ArrowRight, KeyRound, Mail, RotateCw, User, UserRound } from 'lucide-react';
import Card from '../../components/ui/Card';
import Input from '../../components/ui/Input';
import Button from '../../components/ui/Button';
import { isSupabaseConfigured } from '../../lib/supabaseClient';
import { PreviewRunner } from '../../features/assessment-runner/preview-runner';
import { PREVIEW_ACCESS_CODE } from '../../features/assessment-builder/lib/preview-protocol';
import {
  OTP_MAX_LENGTH,
  OTP_MIN_LENGTH,
  useCandidateOtpLogin,
} from '../../features/candidate-auth/use-candidate-otp-login';

export default function Login() {
  const [searchParams] = useSearchParams();
  if (searchParams.get('code') === PREVIEW_ACCESS_CODE) {
    return <PreviewRunner />;
  }
  return <CandidateLogin initialAccessCode={(searchParams.get('code') || '').trim()} />;
}

function StepIndicator({ step }) {
  const active = 'text-primary-text font-semibold';
  return (
    <ol className="mb-4 flex items-center gap-2 text-xs text-muted" aria-label="Sign-in progress">
      <li className={step === 'details' ? active : ''} aria-current={step === 'details' ? 'step' : undefined}>
        1 Your details
      </li>
      <li aria-hidden="true" className="h-px w-6 bg-muted/50" />
      <li className={step === 'code' ? active : ''} aria-current={step === 'code' ? 'step' : undefined}>
        2 Verify email
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
        <div className="mb-6">
          <h1 className="text-xl font-semibold tracking-tight text-foreground">
            {step === 'details' ? 'Welcome to Your Assessment' : 'Check your inbox'}
          </h1>
          <p className="text-sm text-muted mt-2 leading-relaxed">
            {step === 'details'
              ? 'Before you begin, please enter your details below to access your assessment. Please enter your full name as it appears on your application and enter the email address you used when applying.'
              : 'Enter the code we emailed you to continue to your assessment.'}
          </p>
        </div>

        <Card variant="elevated" padding="p-4 sm:p-6">
          <StepIndicator step={step} />

          {!isSupabaseConfigured && (
            <p className="mb-4 rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-warning">
              Email verification is not configured. Contact support.
            </p>
          )}

          {step === 'details' ? (
            <form onSubmit={submitDetails} className="space-y-4" noValidate>
              <Input
                label="Access Code"
                icon={KeyRound}
                placeholder="e.g. HM-ABCDEF-1"
                value={identity.accessCode}
                onChange={(e) => login.updateField('accessCode', e.target.value)}
                className="tabular-data"
                autoComplete="off"
                disabled={loading}
                required
              />
              <Input
                label="First Name"
                icon={UserRound}
                placeholder="What should we call you?"
                value={identity.firstName}
                onChange={(e) => login.updateField('firstName', e.target.value)}
                autoComplete="given-name"
                maxLength={100}
                disabled={loading}
                required
              />
              <Input
                label="Full Name"
                icon={User}
                placeholder="Name as HR should see it on reports"
                value={identity.fullName}
                onChange={(e) => login.updateField('fullName', e.target.value)}
                autoComplete="name"
                maxLength={255}
                disabled={loading}
                required
              />
              <Input
                label="Email"
                type="email"
                icon={Mail}
                placeholder="you@example.com"
                value={identity.email}
                onChange={(e) => login.updateField('email', e.target.value)}
                autoComplete="email"
                inputMode="email"
                disabled={loading}
                required
              />
              <p className="rounded-md border border-border bg-surface-raised px-3 py-2 text-xs leading-relaxed text-muted">
                <span className="font-semibold text-foreground">Disclaimer:</span> Assessment results are generated
                based on your responses and should be interpreted within the context of the organization&apos;s overall
                selection process. MindQ does not guarantee or determine any employment outcome based on the results of
                this assessment. By proceeding, you acknowledge that you understand the purpose of the assessment and
                agree to complete it to the best of your ability.
              </p>
              <FormError message={login.error} />
              <Button
                type="submit"
                className="w-full"
                isLoading={loading}
                disabled={!login.canSend || !isSupabaseConfigured}
              >
                Send verification code
                {!loading && <ArrowRight className="w-4 h-4" aria-hidden="true" />}
              </Button>
            </form>
          ) : (
            <form onSubmit={submitCode} className="space-y-4" noValidate>
              <p className="text-sm text-muted">
                Code sent to <span className="font-medium text-foreground break-all">{identity.email.trim()}</span>
              </p>
              <div>
                <label htmlFor="candidate-otp" className="metric-label mb-1.5 block">
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
                  className="block h-12 w-full rounded-md border border-border bg-canvas px-3 text-center font-mono text-xl tracking-[0.4em] tabular-nums text-foreground placeholder:text-muted/60 transition-colors focus:outline-none focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/50 disabled:opacity-60"
                />
                <p id="candidate-otp-hint" className="mt-2 text-xs text-muted">
                  {OTP_MIN_LENGTH}-digit code. Check spam if it does not arrive within a minute.
                </p>
              </div>
              <FormError message={login.error} />
              <Button type="submit" className="w-full" isLoading={loading} disabled={!login.canVerify}>
                Verify and continue
                {!loading && <ArrowRight className="w-4 h-4" aria-hidden="true" />}
              </Button>
              <div className="flex items-center justify-between gap-2 pt-1">
                <button
                  type="button"
                  onClick={login.editDetails}
                  disabled={loading}
                  className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs text-muted transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-50"
                >
                  <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
                  Edit details
                </button>
                <button
                  type="button"
                  onClick={() => void login.resendCode()}
                  disabled={loading || login.cooldown > 0}
                  className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs text-primary-text transition-colors hover:underline focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-not-allowed disabled:text-muted disabled:no-underline"
                >
                  <RotateCw className="h-3.5 w-3.5" aria-hidden="true" />
                  {login.cooldown > 0 ? `Resend in ${login.cooldown}s` : 'Resend code'}
                </button>
              </div>
            </form>
          )}
        </Card>
        <p className="text-center text-xs text-muted mt-4 leading-relaxed">
          If you experience any technical difficulties while accessing or completing the assessment, please click
          &lsquo;Technical Support&rsquo; to contact our technical support team.
        </p>
      </div>
    </div>
  );
}
