import React from 'react';

const FOOTER_LINES = [
  'MindQ (Pvt) Ltd',
  'Level 35, West Tower,',
  'World Trade Center,',
  'Colombo 01,',
  'Sri Lanka.',
];

/**
 * Shared platform footer with company address and support contact.
 */
export default function Footer() {
  return (
    <footer className="mt-auto border-t border-border bg-transparent px-3 py-6 sm:px-4">
      <div className="mx-auto max-w-3xl text-center text-[11px] leading-relaxed text-muted">
        {FOOTER_LINES.map((line) => (
          <p key={line}>{line}</p>
        ))}
        <p className="mt-1">
          For support inquiries:{' '}
          <a
            href="mailto:support@mindqtalent.com"
            className="underline decoration-muted/50 underline-offset-2 transition-colors hover:text-foreground"
          >
            support@mindqtalent.com
          </a>
        </p>
      </div>
    </footer>
  );
}
