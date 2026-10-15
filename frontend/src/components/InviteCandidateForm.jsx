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
    event.preventDefault();
    const candidateEmail = email.trim();
    if (!candidateEmail || !packageId) return;
    if (!corporateId) {
      toast({ title: 'Invite failed', description: 'No corporate session.', variant: 'error' });
      return;
    }
    setSending(true);
    try {
      await adminApi.inviteCandidate({
        candidateEmail,
        packageId,
        corporateId,
      });
      setEmail('');
      toast({ title: 'Invite sent', variant: 'success' });
      onInvited?.();
    } catch (err) {
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
      <Button type="submit" size="sm" className="shrink-0" isLoading={sending} disabled={!email.trim()}>
        {sending ? 'Sending...' : 'Send Invite'}
      </Button>
    </form>
  );
}
