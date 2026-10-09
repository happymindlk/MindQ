import React from 'react';
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import MindQReport from './mindq-report';
import { DISCLAIMER_BODY, DISCLAIMER_TITLE, FOOTER_NOTICE } from './report-copy';

const SPEC_DISCLAIMER =
  "Important: Use of Assessment Results. The results of this psychometric assessment are intended to provide additional insights into a candidate's behavioural, cognitive, and personality characteristics and should be considered as part of the overall recruitment and selection process. MindQ does not make or determine employment decisions based on assessment results. The final decision remains with the organization.";

const SPEC_FOOTER =
  'This is an automatically generated report. The contents of this report must not be edited, altered, or modified without prior written authorization from MindQ.';

const BASE = {
  candidate_id: '00000000-0000-0000-0000-000000000001',
  company_name: 'Acme Holdings',
  candidate_name: 'Jane Doe',
  candidate_email: 'jane@example.com',
  target_role: 'Analyst',
  company_logo_url: 'https://cdn.example.com/acme.png',
  jd_eval_status: 'ok',
  ai_summary: 'Strong analytical candidate.',
  completed_assessments: [
    {
      id: 'm1',
      title: 'Numerical Reasoning',
      category: 'cognitive',
      category_label: 'Cognitive',
      completed_at: '2026-10-01T09:00:00Z',
    },
    {
      id: 'm2',
      title: 'Work Style Inventory',
      category: 'personality',
      category_label: 'Personality',
      completed_at: '2026-10-01T10:00:00Z',
    },
  ],
  competency_groups: [
    {
      key: 'cognitive',
      label: 'Cognitive',
      average_score: 82.5,
      assessments: [
        { id: 'm1', title: 'Numerical Reasoning', score: 90 },
        { id: 'm3', title: 'Verbal Reasoning', score: 75 },
      ],
      narrative: 'Jane achieved an average of 82.5% across 2 cognitive assessments.',
    },
    {
      key: 'personality',
      label: 'Personality',
      average_score: null,
      assessments: [{ id: 'm2', title: 'Work Style Inventory', score: null }],
      narrative: 'Scores pending.',
    },
  ],
};

describe('report copy', () => {
  it('matches the contractual disclaimer and footer text exactly', () => {
    expect(`${DISCLAIMER_TITLE} ${DISCLAIMER_BODY}`).toBe(SPEC_DISCLAIMER);
    expect(FOOTER_NOTICE).toBe(SPEC_FOOTER);
  });
});

describe('MindQReport', () => {
  it('renders nothing without data', () => {
    const { container } = render(<MindQReport data={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders branding, disclaimer, and footer', () => {
    const { container } = render(<MindQReport data={BASE} />);
    expect(screen.getByAltText('Acme Holdings logo')).toHaveAttribute(
      'src',
      'https://cdn.example.com/acme.png',
    );
    expect(container.querySelector('.mq-disclaimer').textContent).toBe(SPEC_DISCLAIMER);
    const footer = container.querySelector('.mq-footer');
    expect(within(footer).getByLabelText('MindQ')).toBeInTheDocument();
    expect(within(footer).getByText(SPEC_FOOTER)).toBeInTheDocument();
  });

  it('lists completed assessments with categories', () => {
    render(<MindQReport data={BASE} />);
    const section = screen.getByRole('heading', { name: 'Completed Assessments' }).closest('section');
    expect(within(section).getAllByText('Numerical Reasoning')).toHaveLength(1);
    expect(within(section).getByText('Personality')).toBeInTheDocument();
  });

  it('shows per-assessment scores, group averages, and narratives', () => {
    render(<MindQReport data={BASE} />);
    const cognitive = screen.getByRole('heading', { name: 'Cognitive' }).closest('article');
    expect(within(cognitive).getByText('90%')).toBeInTheDocument();
    expect(within(cognitive).getByText('75%')).toBeInTheDocument();
    expect(within(cognitive).getByText('82.5%')).toBeInTheDocument();
    expect(within(cognitive).getByText(/average of 82.5% across 2 cognitive/)).toBeInTheDocument();

    const personality = screen.getByRole('heading', { name: 'Personality' }).closest('article');
    expect(within(personality).getAllByText('—').length).toBeGreaterThanOrEqual(2);
  });

  it('never mentions AI in report copy', () => {
    const { container } = render(
      <MindQReport
        data={{
          ...BASE,
          ai_summary: null,
          jd_eval_status: 'failed',
          custom_questions: [{ id: 'q1', prompt: 'Explain X', ai_eval_status: 'failed' }],
        }}
      />,
    );
    expect(container.textContent).not.toMatch(/\bAI\b|Gemini/);
    expect(screen.getByText(/Evaluation pending or unavailable/)).toBeInTheDocument();
    expect(screen.getByText(/executive synthesis could not be completed/i)).toBeInTheDocument();
  });

  it('falls back to a monogram for unsafe logo URLs and prefers the inlined logo', () => {
    const { rerender } = render(
      <MindQReport data={{ ...BASE, company_logo_url: 'http://localhost/logo.png' }} />,
    );
    expect(screen.queryByRole('img', { name: /logo/ })).not.toBeInTheDocument();
    rerender(<MindQReport data={BASE} logoSrc="data:image/png;base64,AAAA" />);
    expect(screen.getByAltText('Acme Holdings logo')).toHaveAttribute(
      'src',
      'data:image/png;base64,AAAA',
    );
  });

  it('handles an empty breakdown', () => {
    render(<MindQReport data={{ ...BASE, competency_groups: [], completed_assessments: [] }} />);
    expect(screen.getByText('Competency scores are not available yet.')).toBeInTheDocument();
    expect(screen.getByText('No assessments have been completed yet.')).toBeInTheDocument();
  });
});
