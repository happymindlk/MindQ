import React, { useState } from 'react';
import Button from './ui/Button';
import Input from './ui/Input';
import { useToast } from './ui/useToast';
import { useAuth } from '../context/useAuth';
import { adminApi } from '../lib/adminApi';

/**
 * Dense invite control: email + Send Invite. Used on Library and Tracker.
 */
export default function InviteCandidateForm({
  packageId,
  corporateId: corporateIdProp,
  onInvited,
  compact = false,
}) {
  const { corporateId: sessionCorporateId } = useAuth();
  const corporateId = corporateIdProp || sessionCorporateId;
  const { toast } = useToast();
  const [email, setEmail] = useState('');
  const [sending, setSending] = useState(false);

  const handleSubmit = async (event) => {
    // #region agent log
    const _dbg = {
      packageId,
      corporateId,
      emailFromState: email,
      trimmed: email.trim(),
      sending,
      buttonWouldBeDisabled: !email.trim(),
    };
    console.log('[InviteCandidateForm] submit fired', _dbg);
    fetch('http://127.0.0.1:7914/ingest/7b7bc9f0-a919-4525-9fab-35a7604b1d30', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': 'aa0f3a' },
      body: JSON.stringify({
        sessionId: 'aa0f3a',
        runId: 'pre-fix',
        hypothesisId: 'H1-H3',
        location: 'InviteCandidateForm.jsx:handleSubmit',
        message: 'submit fired',
        data: _dbg,
        timestamp: Date.now(),
      }),
    }).catch(() => {});
    // #endregion
    event.preventDefault();
    const candidateEmail = email.trim();
    if (!candidateEmail || !packageId) {
      // #region agent log
      console.log('[InviteCandidateForm] early exit — empty email or missing packageId', {
        candidateEmail,
        packageId,
        dispatchStatus: 'aborted_validation',
      });
      fetch('http://127.0.0.1:7914/ingest/7b7bc9f0-a919-4525-9fab-35a7604b1d30', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': 'aa0f3a' },
        body: JSON.stringify({
          sessionId: 'aa0f3a',
          runId: 'pre-fix',
          hypothesisId: 'H1',
          location: 'InviteCandidateForm.jsx:earlyExit',
          message: 'early exit empty email or packageId',
          data: { candidateEmail, packageId, dispatchStatus: 'aborted_validation' },
          timestamp: Date.now(),
        }),
      }).catch(() => {});
      // #endregion
      return;
    }
    if (!corporateId) {
      // #region agent log
      console.log('[InviteCandidateForm] early exit — no corporateId', {
        packageId,
        dispatchStatus: 'aborted_no_corporate',
      });
      fetch('http://127.0.0.1:7914/ingest/7b7bc9f0-a919-4525-9fab-35a7604b1d30', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': 'aa0f3a' },
        body: JSON.stringify({
          sessionId: 'aa0f3a',
          runId: 'pre-fix',
          hypothesisId: 'H1',
          location: 'InviteCandidateForm.jsx:noCorporate',
          message: 'early exit no corporateId',
          data: { packageId, dispatchStatus: 'aborted_no_corporate' },
          timestamp: Date.now(),
        }),
      }).catch(() => {});
      // #endregion
      toast({ title: 'Invite failed', description: 'No corporate session.', variant: 'error' });
      return;
    }
    setSending(true);
    // #region agent log
    console.log('[InviteCandidateForm] dispatching inviteCandidate', {
      packageId,
      corporateId,
      candidateEmail,
      dispatchStatus: 'calling_api',
    });
    fetch('http://127.0.0.1:7914/ingest/7b7bc9f0-a919-4525-9fab-35a7604b1d30', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': 'aa0f3a' },
      body: JSON.stringify({
        sessionId: 'aa0f3a',
        runId: 'pre-fix',
        hypothesisId: 'H5',
        location: 'InviteCandidateForm.jsx:beforeApi',
        message: 'dispatching inviteCandidate',
        data: { packageId, corporateId, candidateEmail, dispatchStatus: 'calling_api' },
        timestamp: Date.now(),
      }),
    }).catch(() => {});
    // #endregion
    try {
      await adminApi.inviteCandidate({
        candidateEmail,
        packageId,
        corporateId,
      });
      // #region agent log
      console.log('[InviteCandidateForm] inviteCandidate succeeded', {
        packageId,
        dispatchStatus: 'success',
      });
      fetch('http://127.0.0.1:7914/ingest/7b7bc9f0-a919-4525-9fab-35a7604b1d30', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': 'aa0f3a' },
        body: JSON.stringify({
          sessionId: 'aa0f3a',
          runId: 'pre-fix',
          hypothesisId: 'H5',
          location: 'InviteCandidateForm.jsx:apiSuccess',
          message: 'inviteCandidate succeeded',
          data: { packageId, dispatchStatus: 'success' },
          timestamp: Date.now(),
        }),
      }).catch(() => {});
      // #endregion
      setEmail('');
      toast({ title: 'Invite sent', variant: 'success' });
      onInvited?.();
    } catch (err) {
      // #region agent log
      console.log('[InviteCandidateForm] inviteCandidate failed', {
        packageId,
        dispatchStatus: 'error',
        error: err?.message,
      });
      fetch('http://127.0.0.1:7914/ingest/7b7bc9f0-a919-4525-9fab-35a7604b1d30', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': 'aa0f3a' },
        body: JSON.stringify({
          sessionId: 'aa0f3a',
          runId: 'pre-fix',
          hypothesisId: 'H5',
          location: 'InviteCandidateForm.jsx:apiError',
          message: 'inviteCandidate failed',
          data: { packageId, dispatchStatus: 'error', error: err?.message },
          timestamp: Date.now(),
        }),
      }).catch(() => {});
      // #endregion
      toast({
        title: 'Invite failed',
        description: err.message,
        variant: 'error',
      });
    } finally {
      setSending(false);
    }
  };

    return (
    <form onSubmit={handleSubmit} className="flex items-center gap-2 min-w-0">
      <div className={compact ? 'w-52 shrink-0' : 'flex-1 min-w-0'}>
        <Input
          type="email"
          placeholder="candidate@company.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          aria-label="Candidate email"
          required
          autoComplete="off"
        />
      </div>
      <Button
        type="submit"
        size="sm"
        className="shrink-0"
        isLoading={sending}
        disabled={!email.trim()}
        onClick={() => {
          // #region agent log
          console.log('[InviteCandidateForm] button click', {
            packageId,
            corporateId,
            emailFromState: email,
            disabled: !email.trim(),
            dispatchStatus: 'button_click',
          });
          fetch('http://127.0.0.1:7914/ingest/7b7bc9f0-a919-4525-9fab-35a7604b1d30', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': 'aa0f3a' },
            body: JSON.stringify({
              sessionId: 'aa0f3a',
              runId: 'pre-fix',
              hypothesisId: 'H2-H4',
              location: 'InviteCandidateForm.jsx:buttonClick',
              message: 'Send Invite button click',
              data: {
                packageId,
                corporateId,
                emailFromState: email,
                disabled: !email.trim(),
                dispatchStatus: 'button_click',
              },
              timestamp: Date.now(),
            }),
          }).catch(() => {});
          // #endregion
        }}
      >
        {sending ? 'Sending...' : 'Send Invite'}
      </Button>
    </form>
  );
}
