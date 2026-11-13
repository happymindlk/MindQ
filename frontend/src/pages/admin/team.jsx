import React, { useCallback, useEffect, useId, useState } from 'react';
import { AlertTriangle, Shield, UserPlus } from 'lucide-react';
import Button from '../../components/ui/Button';
import EmptyState from '../../components/ui/EmptyState';
import Input from '../../components/ui/Input';
import Modal from '../../components/ui/Modal';
import PageHeader from '../../components/ui/PageHeader';
import Skeleton from '../../components/ui/Skeleton';
import { useToast } from '../../components/ui/useToast';
import { friendlyErrorMessage } from '../../lib/friendly-error';
import { adminApi } from '../../lib/adminApi';

function formatCreatedAt(value) {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return '—';
  }
}

function SourceBadge({ source }) {
  if (source === 'env') {
    return (
      <span className="inline-flex items-center rounded-md border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-200">
        System / Env Managed
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
      Database
    </span>
  );
}

function TeamTableSkeleton() {
  return (
    <div
      className="overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900"
      role="status"
      aria-label="Loading Super Admins"
    >
      <div className="divide-y divide-slate-100 dark:divide-slate-800">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="flex items-center gap-4 px-4 py-3">
            <Skeleton className="h-4 w-48" />
            <Skeleton className="h-4 w-24" />
            <Skeleton className="ml-auto h-8 w-20" />
          </div>
        ))}
      </div>
    </div>
  );
}

export default function AdminTeam() {
  const { toast } = useToast();
  const emailId = useId();
  const [members, setMembers] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [email, setEmail] = useState('');
  const [isAdding, setIsAdding] = useState(false);
  const [revoking, setRevoking] = useState(null);
  const [isRevoking, setIsRevoking] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const rows = await adminApi.listAdminTeam();
      setMembers(rows);
    } catch (err) {
      setError(friendlyErrorMessage(err, 'Could not load Super Admins.'));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleAdd = useCallback(
    async (event) => {
      event.preventDefault();
      const normalized = email.trim().toLowerCase();
      if (!normalized) return;
      setIsAdding(true);
      try {
        const member = await adminApi.addAdmin(normalized);
        setMembers((prev) => {
          const without = prev.filter((row) => row.email !== member.email);
          return [...without, member].sort((a, b) => a.email.localeCompare(b.email));
        });
        setEmail('');
        toast({
          variant: 'success',
          title: 'Super Admin added',
          description: `${member.email} can sign in to the admin portal.`,
        });
      } catch (err) {
        toast({
          variant: 'error',
          title: 'Could not add Super Admin',
          description: friendlyErrorMessage(err, 'Something went wrong. Try again.'),
        });
      } finally {
        setIsAdding(false);
      }
    },
    [email, toast],
  );

  const confirmRevoke = useCallback(async () => {
    if (!revoking?.user_id) return;
    setIsRevoking(true);
    try {
      await adminApi.revokeAdmin(revoking.user_id);
      setMembers((prev) => prev.filter((row) => row.user_id !== revoking.user_id));
      toast({
        variant: 'success',
        title: 'Access revoked',
        description: `${revoking.email} no longer has Super Admin access.`,
      });
      setRevoking(null);
    } catch (err) {
      toast({
        variant: 'error',
        title: 'Could not revoke access',
        description: friendlyErrorMessage(err, 'Something went wrong. Try again.'),
      });
    } finally {
      setIsRevoking(false);
    }
  }, [revoking, toast]);

  let body;
  if (isLoading && members.length === 0) {
    body = <TeamTableSkeleton />;
  } else if (error) {
    body = (
      <div
        role="alert"
        className="flex flex-col items-center gap-3 rounded-lg border border-danger/30 bg-danger/5 px-4 py-8 text-center"
      >
        <AlertTriangle className="h-5 w-5 text-danger" aria-hidden="true" />
        <div>
          <p className="text-sm font-semibold text-foreground">Could not load Super Admins</p>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{error}</p>
        </div>
        <Button variant="secondary" size="sm" onClick={load}>
          Retry
        </Button>
      </div>
    );
  } else if (members.length === 0) {
    body = (
      <div className="rounded-lg border border-dashed border-slate-300 dark:border-slate-800">
        <EmptyState
          icon={Shield}
          title="No Super Admins yet"
          description="Add an email to grant Super Admin access to the ops portal."
        />
      </div>
    );
  } else {
    body = (
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <table className="min-w-full text-left text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-xs font-medium uppercase tracking-wide text-slate-500 dark:border-slate-800 dark:bg-slate-950/50 dark:text-slate-400">
            <tr>
              <th scope="col" className="px-4 py-3 font-medium">
                Email
              </th>
              <th scope="col" className="hidden px-4 py-3 font-medium sm:table-cell">
                Name
              </th>
              <th scope="col" className="px-4 py-3 font-medium">
                Source
              </th>
              <th scope="col" className="hidden px-4 py-3 font-medium md:table-cell">
                Added
              </th>
              <th scope="col" className="px-4 py-3 font-medium text-right">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {members.map((member) => (
              <tr key={member.user_id || `env:${member.email}`}>
                <td className="px-4 py-3 font-medium text-foreground">{member.email}</td>
                <td className="hidden px-4 py-3 text-slate-600 dark:text-slate-300 sm:table-cell">
                  {member.name || '—'}
                </td>
                <td className="px-4 py-3">
                  <SourceBadge source={member.source} />
                </td>
                <td className="hidden px-4 py-3 text-slate-500 dark:text-slate-400 md:table-cell">
                  {formatCreatedAt(member.created_at)}
                </td>
                <td className="px-4 py-3 text-right">
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    disabled={!member.can_revoke || !member.user_id}
                    onClick={() => setRevoking(member)}
                    title={
                      member.source === 'env'
                        ? 'System / Env Managed — revoke disabled'
                        : !member.can_revoke
                          ? 'You cannot revoke your own access'
                          : 'Revoke Super Admin access'
                    }
                  >
                    Revoke
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Team / Admins"
        description="Grant or revoke Super Admin access. Env-managed emails cannot be revoked from the UI."
      />

      <form
        onSubmit={handleAdd}
        className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:flex-row sm:items-end dark:border-slate-800 dark:bg-slate-900"
      >
        <div className="min-w-0 flex-1">
          <label htmlFor={emailId} className="metric-label mb-1.5 block">
            Super Admin email
          </label>
          <Input
            id={emailId}
            type="email"
            autoComplete="off"
            placeholder="ops@company.com"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            disabled={isAdding}
            required
          />
        </div>
        <Button type="submit" variant="accent" size="md" isLoading={isAdding} disabled={!email.trim()}>
          <UserPlus className="h-3.5 w-3.5" aria-hidden="true" />
          Add Admin
        </Button>
      </form>

      {body}

      <Modal
        isOpen={revoking !== null}
        onClose={() => !isRevoking && setRevoking(null)}
        title={revoking ? `Revoke ${revoking.email}?` : 'Revoke access'}
        actions={
          <>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => setRevoking(null)}
              disabled={isRevoking}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="danger"
              size="sm"
              isLoading={isRevoking}
              onClick={confirmRevoke}
            >
              Revoke access
            </Button>
          </>
        }
      >
        <p className="text-sm text-neutral-600 dark:text-neutral-300">
          {revoking?.email} will lose Super Admin portal access immediately. They will need to be
          re-added before they can sign in again.
        </p>
      </Modal>
    </div>
  );
}
