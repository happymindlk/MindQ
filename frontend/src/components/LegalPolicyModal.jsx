import React from 'react';
import Modal from './ui/Modal';
import { getLegalDocument } from '../content/legalPolicies';

/**
 * Scrollable modal for Privacy Policy or Terms & Conditions.
 * Opens as an overlay so parent form state (e.g. login fields) is preserved.
 *
 * @param {object} props
 * @param {boolean} props.isOpen
 * @param {() => void} props.onClose
 * @param {'privacy' | 'terms' | null} props.documentId
 */
export default function LegalPolicyModal({ isOpen, onClose, documentId }) {
  const doc = documentId ? getLegalDocument(documentId) : null;

  return (
    <Modal
      isOpen={Boolean(isOpen && doc)}
      onClose={onClose}
      title={doc?.title ?? 'Legal'}
      contentClassName="max-w-2xl max-h-[85vh] flex flex-col"
      actions={
        <button
          type="button"
          onClick={onClose}
          className="inline-flex h-9 items-center rounded-md border border-border bg-surface px-3 text-sm font-medium text-foreground transition-colors hover:bg-surface-raised focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          Close
        </button>
      }
    >
      {doc ? (
        <div className="max-h-[60vh] space-y-5 overflow-y-auto pr-1 text-sm leading-relaxed text-foreground">
          {doc.sections.map((section, index) => (
            <section key={`${doc.id}-${section.heading ?? 'intro'}-${index}`} className="space-y-2">
              {section.heading ? (
                <h3 className="text-sm font-semibold text-foreground">{section.heading}</h3>
              ) : null}
              {section.paragraphs.map((paragraph) => (
                <p key={paragraph.slice(0, 48)} className="text-muted">
                  {paragraph}
                </p>
              ))}
              {section.bullets?.length ? (
                <ul className="list-disc space-y-1.5 pl-5 text-muted">
                  {section.bullets.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : null}
            </section>
          ))}
        </div>
      ) : null}
    </Modal>
  );
}
