import React, { memo } from 'react';
import { useNavigate } from 'react-router-dom';
import { FileText, Users } from 'lucide-react';
import ClientStatusBadge from './client-status-badge';
import { isReportReady } from '../../features/mindq-report/report-readiness';

function formatScore(score) {
  return score == null ? '—' : `${Number(score).toFixed(1)}%`;
}

/** @param {{ candidates: Array<object> }} props */
function CandidateTable({ candidates }) {
  const navigate = useNavigate();

  if (candidates.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 rounded-md border border-dashed border-border px-4 py-8 text-center">
        <Users className="h-5 w-5 text-muted" aria-hidden="true" />
        <p className="text-sm font-medium text-foreground">No candidates yet</p>
        <p className="text-xs text-muted">
          Share the candidate link and PIN above. Candidates appear here once they sign in.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead className="bg-surface-raised text-[11px] uppercase tracking-wider text-muted">
          <tr>
            <th scope="col" className="px-4 py-2 font-medium">Candidate Name</th>
            <th scope="col" className="px-4 py-2 font-medium">Email</th>
            <th scope="col" className="px-4 py-2 font-medium">Status</th>
            <th scope="col" className="px-4 py-2 text-right font-medium">Score</th>
            <th scope="col" className="px-4 py-2 text-right font-medium">
              <span className="sr-only">Action</span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {candidates.map((c) => {
            const ready = isReportReady(c);
            return (
              <tr key={c.candidate_id} className="transition-colors hover:bg-surface-raised/60">
                <td className="px-4 py-2.5 font-medium text-foreground">{c.name}</td>
                <td className="max-w-[16rem] truncate px-4 py-2.5 text-muted" title={c.email}>
                  {c.email}
                </td>
                <td className="px-4 py-2.5">
                  <ClientStatusBadge status={c.status} />
                </td>
                <td className="px-4 py-2.5 text-right font-mono tabular-nums text-foreground">
                  {formatScore(c.raw_score)}
                </td>
                <td className="px-4 py-2.5 text-right">
                  <button
                    type="button"
                    disabled={!ready}
                    onClick={() => navigate(c.report_path || `/client/candidates/${c.candidate_id}`)}
                    title={ready ? 'Open MindQ Report' : 'Available once the candidate completes all assessments'}
                    className="inline-flex h-7 items-center gap-1.5 rounded-md bg-indigo-600 px-2.5 text-xs font-medium text-white transition-colors hover:bg-indigo-700 active:bg-indigo-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 focus-visible:ring-offset-2 focus-visible:ring-offset-canvas disabled:cursor-not-allowed disabled:bg-surface-raised disabled:text-muted"
                  >
                    <FileText className="h-3.5 w-3.5" aria-hidden="true" />
                    View Report
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default memo(CandidateTable);
