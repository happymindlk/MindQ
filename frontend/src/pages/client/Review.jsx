import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { CheckCircle2, Shield } from 'lucide-react';
import EmptyState from '../../components/ui/EmptyState';
import PageHeader from '../../components/ui/PageHeader';
import Button from '../../components/ui/Button';
import Badge from '../../components/ui/Badge';
import { SkeletonRows } from '../../components/ui/Skeleton';
import { clientApi } from '../../lib/clientApi';

export default function ClientReview() {
  const { packageToken } = useParams();
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [approving, setApproving] = useState(false);
  const [approveError, setApproveError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await clientApi.getBlindReview(packageToken);
        if (!cancelled) setPayload(data);
      } catch (err) {
        if (!cancelled) setError(err.message || 'Review unavailable');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [packageToken]);

  const handleApprove = async () => {
    setApproving(true);
    setApproveError(null);
    try {
      await clientApi.approveBlindReview(packageToken);
      setPayload((prev) =>
        prev
          ? {
              ...prev,
              client_approved: true,
              reviewed_at: new Date().toISOString(),
            }
          : prev,
      );
    } catch (err) {
      setApproveError(err.message || 'Approval failed');
    } finally {
      setApproving(false);
    }
  };

  const approved = Boolean(payload?.client_approved);

  return (
    <div className="min-h-screen bg-canvas text-foreground">
      <div className="max-w-3xl mx-auto px-4 py-8 space-y-4">
        <PageHeader
          title={payload?.title || 'Technical review'}
          description={payload?.corporate_name || undefined}
        />

        {loading && <SkeletonRows rows={6} />}

        {!loading && error && (
          <EmptyState icon={Shield} title="Unavailable" description={error} />
        )}

        {!loading && payload && (
          <>
            <div className="rounded-lg border border-border bg-surface-raised px-4 py-3 flex flex-wrap items-center justify-between gap-3">
              {approved ? (
                <Badge variant="completed" showDot>
                  Approved by Client
                </Badge>
              ) : (
                <>
                  <p className="text-sm text-muted">
                    Review the technical items below, then approve this assessment suite.
                  </p>
                  <Button
                    type="button"
                    size="sm"
                    onClick={handleApprove}
                    disabled={approving}
                    className="shrink-0"
                  >
                    <CheckCircle2 className="w-3.5 h-3.5 mr-1.5" />
                    {approving ? 'Approving…' : 'Approve Assessment'}
                  </Button>
                </>
              )}
            </div>
            {approveError && (
              <p className="text-sm text-rose-400">{approveError}</p>
            )}

            <ol className="rounded-lg border border-border bg-surface-raised divide-y divide-border">
              {payload.questions.length === 0 && (
                <li>
                  <EmptyState title="No technical items" className="py-10" />
                </li>
              )}
              {payload.questions.map((q, index) => (
                <li key={q.id || index} className="px-4 py-3">
                  <p className="text-[11px] uppercase tracking-wider text-muted">
                    {String(index + 1).padStart(2, '0')} · {q.question_type}
                  </p>
                  <p className="text-sm text-foreground mt-1">{q.prompt}</p>
                  {q.options?.length > 0 && (
                    <ul className="mt-2 space-y-1">
                      {q.options.map((opt) => (
                        <li
                          key={opt}
                          className="text-xs text-muted border border-border rounded-md px-2 py-1.5"
                        >
                          {opt}
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ol>
          </>
        )}
      </div>
    </div>
  );
}
