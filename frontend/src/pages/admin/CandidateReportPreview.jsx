import React, { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Download, FileText } from 'lucide-react';
import Button from '../../components/ui/Button';
import EmptyState from '../../components/ui/EmptyState';
import PageHeader from '../../components/ui/PageHeader';
import { SkeletonRows } from '../../components/ui/Skeleton';
import { useToast } from '../../components/ui/useToast';
import { adminApi } from '../../lib/adminApi';
import MindQReport from '../../features/mindq-report/mindq-report';
import { downloadMindQReport } from '../../features/mindq-report/render-report-pdf';
import { REPORT_TITLE } from '../../features/mindq-report/report-copy';
import { useReportData } from '../../features/mindq-report/use-report-data';

/**
 * Polished full-page MindQ Report preview for admins, reached from
 * Assessment History. Same layout as the HR-facing client preview
 * (`pages/client/candidate-report.jsx`) so the report never drifts between
 * preview and downloaded PDF.
 */
export default function CandidateReportPreview() {
  const { candidateId } = useParams();
  const navigate = useNavigate();
  const { toast } = useToast();
  const { data, error, loading, retry } = useReportData(candidateId, adminApi.getReportData);
  const [downloading, setDownloading] = useState(false);

  const onDownload = async () => {
    if (!data) return;
    setDownloading(true);
    try {
      await downloadMindQReport(() => adminApi.getReportData(candidateId));
      toast({
        title: 'Report ready',
        description: 'Assessment report PDF downloaded.',
        variant: 'success',
      });
    } catch (err) {
      toast({
        title: 'Download failed',
        description: err instanceof Error ? err.message : 'Could not generate the PDF.',
        variant: 'error',
      });
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="print:hidden">
        <PageHeader
          title={data?.candidate_full_name || REPORT_TITLE}
          description={data ? `${REPORT_TITLE} · ${data.target_role || data.company_name}` : undefined}
          actions={
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="sm" onClick={() => navigate('/admin/history')}>
                <ArrowLeft className="h-3.5 w-3.5" />
                Assessment History
              </Button>
              <Button size="sm" onClick={onDownload} isLoading={downloading} disabled={!data}>
                {!downloading && <Download className="h-3.5 w-3.5" />}
                Download PDF
              </Button>
            </div>
          }
        />
      </div>

      {loading && <SkeletonRows rows={8} />}

      {!loading && error && (
        <EmptyState
          icon={FileText}
          title="Report unavailable"
          description={error}
          actionLabel="Retry"
          onAction={retry}
        />
      )}

      {!loading && !error && data && (
        <div className="overflow-x-auto rounded-lg border border-border bg-surface-raised p-4 sm:p-8 print:overflow-visible print:rounded-none print:border-0 print:bg-white print:p-0">
          <div className="mx-auto w-fit rounded-sm shadow-lg ring-1 ring-black/5 print:w-full print:shadow-none print:ring-0">
            <MindQReport data={data} />
          </div>
        </div>
      )}
    </div>
  );
}
