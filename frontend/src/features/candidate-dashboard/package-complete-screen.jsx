import React from 'react';
import { CheckCircle2 } from 'lucide-react';

/**
 * Final candidate exit when every module in the package is COMPLETED.
 * Intentionally has no navigation CTA — the evaluation is closed.
 *
 * @param {{ companyName?: string | null }} props
 */
export default function PackageCompleteScreen({ companyName }) {
  const org = (companyName || '').trim() || 'the hiring organization';

  return (
    <div className="mx-auto flex w-full max-w-md flex-col items-center py-16 text-center">
      <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full border border-success/25 bg-success/15">
        <CheckCircle2 className="h-7 w-7 text-success" aria-hidden />
      </div>
      <h1 className="text-lg font-semibold text-foreground">You&apos;ve completed all assessments!</h1>
      <p className="mt-3 text-sm leading-relaxed text-muted">
        Thank you for taking the time to complete your candidate evaluation. Your responses have been
        submitted to {org}. You may safely close this window.
      </p>
    </div>
  );
}
