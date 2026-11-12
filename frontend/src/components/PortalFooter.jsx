import React, { useState } from 'react';
import LegalPolicyModal from './LegalPolicyModal';

/**
 * Minimal legal footer for candidate and HR portal shells.
 * Privacy / Terms open in a modal so active sessions are not interrupted.
 */
export default function PortalFooter() {
  const [legalDoc, setLegalDoc] = useState(null);
  const appVersion =
    typeof import.meta !== 'undefined' && import.meta.env?.VITE_APP_VERSION
      ? String(import.meta.env.VITE_APP_VERSION).trim()
      : '';

  return (
    <>
      <footer className="border-t border-border bg-surface/80">
        <div className="mx-auto flex max-w-4xl flex-col items-center gap-2 px-4 py-4 text-center">
          <nav aria-label="Legal" className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-xs">
            <button
              type="button"
              onClick={() => setLegalDoc('privacy')}
              className="text-muted transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded-sm"
            >
              Privacy Policy
            </button>
            <span className="text-border" aria-hidden="true">
              |
            </span>
            <button
              type="button"
              onClick={() => setLegalDoc('terms')}
              className="text-muted transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded-sm"
            >
              Terms &amp; Conditions
            </button>
          </nav>
          <p className="text-[11px] text-muted">
            2026 © MindQ Talent
            {appVersion ? ` · v${appVersion}` : null}
          </p>
        </div>
      </footer>
      <LegalPolicyModal
        isOpen={Boolean(legalDoc)}
        documentId={legalDoc}
        onClose={() => setLegalDoc(null)}
      />
    </>
  );
}
