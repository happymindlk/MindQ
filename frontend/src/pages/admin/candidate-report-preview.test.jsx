import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import CandidateReportPreview from './CandidateReportPreview';

const { getReportData, toast } = vi.hoisted(() => ({
  getReportData: vi.fn(),
  toast: vi.fn(),
}));

vi.mock('../../lib/adminApi', () => ({
  adminApi: { getReportData },
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
  risks_and_antipatterns: [],
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
  toast.mockReset();
  getReportData.mockResolvedValue(REPORT);
});

describe('CandidateReportPreview', () => {
  it('renders the polished MindQReport for admins via adminApi', async () => {
    renderPreview();
    expect(await screen.findByText('Strong reasoning overall.')).toBeInTheDocument();
    expect(getReportData).toHaveBeenCalledWith('cand-1');
    expect(screen.getAllByRole('heading', { level: 1, name: 'Jane Doe' }).length).toBeGreaterThan(0);
    expect(screen.getByText(/MindQ \(Pvt\.\) Ltd\./)).toBeInTheDocument();
  });

  it('returns to Assessment History', async () => {
    const user = userEvent.setup();
    renderPreview();
    await screen.findByText('Strong reasoning overall.');
    await user.click(screen.getByRole('button', { name: /Assessment History/ }));
    expect(await screen.findByRole('heading', { name: 'Assessment History' })).toBeInTheDocument();
  });
});
