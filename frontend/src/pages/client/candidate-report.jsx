import React, { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Download, FileText } from 'lucide-react';
import Button from '../../components/ui/Button';
import EmptyState from '../../components/ui/EmptyState';
import PageHeader from '../../components/ui/PageHeader';
import { SkeletonRows } from '../../components/ui/Skeleton';
import { useToast } from '../../components/ui/useToast';
import { clientApi } from '../../lib/clientApi';
import MindQReport from '../../features/mindq-report/mindq-report';
import { renderReportPdf, saveBlob } from '../../features/mindq-report/render-report-pdf';
import { REPORT_TITLE } from '../../features/mindq-report/report-copy';
import { useReportData } from '../../features/mindq-report/use-report-data';

export default function ClientCandidateReport() {
  const { candidateId } = useParams();
  const navigate = useNavigate();
  const { toast } = useToast();
  const { data, error, loading, retry } = useReportData(candidateId, clientApi.getReportData);
  const [downloading, setDownloading] = useState(false);

  const onDownload = async () => {
    if (!data) return;
    setDownloading(true);
    try {
      const { blob, filename } = await renderReportPdf(data);
      saveBlob(blob, filename);
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
      <PageHeader
        title={data?.candidate_name || REPORT_TITLE}
        description={data ? `${REPORT_TITLE} · ${data.target_role || data.company_name}` : undefined}
        actions={
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => navigate('/client/dashboard')}>
              <ArrowLeft className="h-3.5 w-3.5" />
              Dashboard
            </Button>
            <Button size="sm" onClick={onDownload} isLoading={downloading} disabled={!data}>
              {!downloading && <Download className="h-3.5 w-3.5" />}
              Download PDF
            </Button>
          </div>
        }
      />

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
        <div className="overflow-x-auto rounded-lg border border-border bg-surface-raised p-4 sm:p-8">
          <div className="mx-auto w-fit rounded-sm shadow-lg ring-1 ring-black/5">
            <MindQReport data={data} />
          </div>
        </div>
      )}
    </div>
  );
}
