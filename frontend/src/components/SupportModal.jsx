import React, { useState } from 'react';
import { LifeBuoy } from 'lucide-react';
import Modal from './ui/Modal';
import Button from './ui/Button';

export default function SupportModal() {
  const [open, setOpen] = useState(false);
  const [details, setDetails] = useState('');
  const [sent, setSent] = useState(false);

  const handleSubmit = (e) => {
    e.preventDefault();
    const payload = {
      details,
      candidateId: localStorage.getItem('candidateId'),
      path: window.location.pathname,
      userAgent: navigator.userAgent,
      at: new Date().toISOString(),
    };
    console.info('support/submit (UI only — no ticket API yet)', payload);
    setSent(true);
  };

  return (
    <>
      <button
        type="button"
        onClick={() => { setOpen(true); setSent(false); }}
        className="fixed bottom-6 right-6 z-50 flex items-center gap-2 px-4 py-3 rounded-full bg-indigo-600 text-white shadow-lg shadow-indigo-500/30 hover:bg-indigo-500"
      >
        <LifeBuoy className="w-5 h-5" />
        <span className="text-sm font-medium hidden sm:inline">Technical support</span>
      </button>

      <Modal
        isOpen={open}
        onClose={() => setOpen(false)}
        title="Report a technical issue"
        actions={
          sent ? (
            <Button onClick={() => setOpen(false)}>Close</Button>
          ) : (
            <>
              <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
              <Button onClick={handleSubmit} disabled={!details.trim()}>Submit</Button>
            </>
          )
        }
      >
        {sent ? (
          <p>Your report was captured with session metadata. Engineering alerting is not wired yet; keep this tab open so you do not lose progress.</p>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-3">
            <p className="text-sm text-slate-400">
              Describe what went wrong. We attach your session id, page, and browser so you do not have to leave the test.
            </p>
            <textarea
              className="w-full h-32 rounded-lg bg-slate-950 border border-slate-700 text-slate-50 text-sm p-3"
              placeholder="e.g. Next button did nothing after question 4…"
              value={details}
              onChange={(e) => setDetails(e.target.value)}
            />
          </form>
        )}
      </Modal>
    </>
  );
}
