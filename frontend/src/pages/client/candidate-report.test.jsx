import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ClientCandidateReport from './candidate-report';

const { getReportData, downloadReport, toast, renderReportPdf } = vi.hoisted(() => ({
  getReportData: vi.fn(),
  downloadReport: vi.fn(),
  toast: vi.fn(),
  renderReportPdf: vi.fn(),
}));

vi.mock('../../lib/clientApi', () => ({
  clientApi: { getReportData, downloadReport },
}));

vi.mock('../../components/ui/useToast', () => ({
  useToast: () => ({ toast }),
}));

vi.mock('../../features/mindq-report/render-report-pdf', () => ({
  renderReportPdf,
  saveBlob: vi.fn(),
}));

const REPORT = {
  candidate_id: 'cand-1',
  company_name: 'Acme Holdings',
  company_logo_url: null,
  candidate_full_name: 'Jane Doe',
  candidate_email: 'jane@example.com',
  target_role: 'Analyst',
  synthesis_status: 'ok',
  total_assessments_completed: 1,
  executive_summary: 'Strong analytical candidate.',
  strengths: ['Fast numerical reasoning.'],
  areas_to_explore: [],
  competency_breakdown: [
    {
      category: 'Cognitive',
      assessment_name: 'Numerical Reasoning',
      score: 82.5,
      performance_summary: 'Strong numerical reasoning.',
    },
  ],
  category_summaries: [],
  custom_questions: [],
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/client/candidates/cand-1/report']}>
      <Routes>
        <Route path="/client/candidates/:candidateId/report" element={<ClientCandidateReport />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  getReportData.mockReset().mockResolvedValue(REPORT);
  downloadReport.mockReset().mockResolvedValue({ isHtml: false, synthesisStatus: 'ok', cacheState: 'HIT' });
  toast.mockReset();
  renderReportPdf.mockReset();
});

describe('ClientCandidateReport download', () => {
  it('downloads the server-rendered PDF, never rendering in the browser', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('Strong analytical candidate.');
    await user.click(screen.getByRole('button', { name: /Download PDF/ }));

    expect(downloadReport).toHaveBeenCalledWith('cand-1');
    expect(renderReportPdf).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: 'Report ready' }));
  });

  it('keeps Download enabled while the narrative is generating and warns', async () => {
    const user = userEvent.setup();
    getReportData.mockResolvedValue({ ...REPORT, executive_summary: '', synthesis_status: 'generating' });
    downloadReport.mockResolvedValue({ isHtml: false, synthesisStatus: 'generating', cacheState: 'BYPASS' });
    renderPage();
    await screen.findByRole('status', { name: 'Generating executive summary' });

    const button = screen.getByRole('button', { name: /Download PDF/ });
    expect(button).toBeEnabled();
    await user.click(button);
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ variant: 'warning', description: expect.stringMatching(/still being generated/) }),
    );
  });

  it('shows the server error when the download is refused', async () => {
    const user = userEvent.setup();
    downloadReport.mockRejectedValue(new Error('Candidate not found'));
    renderPage();
    await screen.findByText('Strong analytical candidate.');
    await user.click(screen.getByRole('button', { name: /Download PDF/ }));
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Download failed', description: 'Candidate not found', variant: 'error' }),
    );
  });
});
