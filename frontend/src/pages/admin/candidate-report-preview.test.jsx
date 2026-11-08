import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import CandidateReportPreview from './CandidateReportPreview';

const { getReportData, downloadReport, toast } = vi.hoisted(() => ({
  getReportData: vi.fn(),
  downloadReport: vi.fn(),
  toast: vi.fn(),
}));

vi.mock('../../lib/adminApi', () => ({
  adminApi: { getReportData, downloadReport },
}));

vi.mock('../../components/ui/useToast', () => ({
  useToast: () => ({ toast }),
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
  category_averages: { Cognitive: 82.5 },
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
  category_summaries: [{ category: 'Cognitive', summary: 'Strong reasoning overall.' }],
  custom_questions: [],
};

function renderPreview() {
  return render(
    <MemoryRouter initialEntries={['/admin/candidates/cand-1/report']}>
      <Routes>
        <Route path="/admin/candidates/:candidateId/report" element={<CandidateReportPreview />} />
        <Route path="/admin/history" element={<h1>Assessment History</h1>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  getReportData.mockReset();
  downloadReport.mockReset();
  toast.mockReset();
  getReportData.mockResolvedValue(REPORT);
  downloadReport.mockResolvedValue({ isHtml: false, synthesisStatus: 'ok' });
});

describe('CandidateReportPreview', () => {
  it('renders the polished MindQReport for admins via adminApi', async () => {
    renderPreview();
    expect(await screen.findByText('Strong reasoning overall.')).toBeInTheDocument();
    expect(getReportData).toHaveBeenCalledWith('cand-1');
    expect(screen.getAllByRole('heading', { level: 1, name: 'Jane Doe' }).length).toBeGreaterThan(0);
    expect(screen.getByText(/MindQ \(Pvt\.\) Ltd\./)).toBeInTheDocument();
  });

  it('shows scores at once and swaps the summary shimmer for text when generation finishes', async () => {
    getReportData
      .mockReset()
      .mockResolvedValueOnce({ ...REPORT, executive_summary: '', synthesis_status: 'generating' })
      .mockResolvedValueOnce(REPORT);
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      renderPreview();
      expect(await screen.findByText('Numerical Reasoning')).toBeInTheDocument();
      expect(screen.getByRole('status', { name: 'Generating executive summary' })).toBeInTheDocument();

      await vi.advanceTimersByTimeAsync(3000);
      expect(await screen.findByText('Strong analytical candidate.')).toBeInTheDocument();
      expect(screen.queryByRole('status', { name: 'Generating executive summary' })).toBeNull();
      expect(getReportData).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('downloads the server-rendered PDF instead of rendering in the browser', async () => {
    const user = userEvent.setup();
    renderPreview();
    await screen.findByText('Strong reasoning overall.');
    await user.click(screen.getByRole('button', { name: /Download PDF/ }));
    expect(downloadReport).toHaveBeenCalledWith('cand-1');
    expect(getReportData).toHaveBeenCalledTimes(1);
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: 'Report ready' }));
  });

  it('keeps Download enabled while generating and warns about the fallback text', async () => {
    const user = userEvent.setup();
    getReportData.mockResolvedValue({ ...REPORT, executive_summary: '', synthesis_status: 'generating' });
    downloadReport.mockResolvedValue({ isHtml: false, synthesisStatus: 'generating' });
    renderPreview();
    await screen.findByRole('status', { name: 'Generating executive summary' });
    const button = screen.getByRole('button', { name: /Download PDF/ });
    expect(button).toBeEnabled();
    await user.click(button);
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ variant: 'warning', description: expect.stringMatching(/still being generated/) }),
    );
  });

  it('surfaces a failed download', async () => {
    const user = userEvent.setup();
    downloadReport.mockRejectedValue(new Error('Too many requests. Try again later.'));
    renderPreview();
    await screen.findByText('Strong reasoning overall.');
    await user.click(screen.getByRole('button', { name: /Download PDF/ }));
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Download failed', variant: 'error' }),
    );
  });

  it('returns to Assessment History', async () => {
    const user = userEvent.setup();
    renderPreview();
    await screen.findByText('Strong reasoning overall.');
    await user.click(screen.getByRole('button', { name: /Assessment History/ }));
    expect(await screen.findByRole('heading', { name: 'Assessment History' })).toBeInTheDocument();
  });
});
