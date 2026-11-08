import React from 'react';
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import MindQReport from './mindq-report';
import {
  FIT_DISCLAIMER,
  FOOTER_ENTITY,
  FOOTER_NOTICE,
  FOOTER_NOTICE_PREFIX,
  REPORT_TITLE,
} from './report-copy';

const SPEC_FOOTER =
  'This is an auto-generated MindQ report. This document cannot be reproduced, edited, or redistributed without the written consent of MindQ (Pvt.) Ltd.';

const SPEC_FIT_DISCLAIMER =
  'This assessment is not an indication of whether the candidate is a good fit. This is merely an analysis of an assessment. You need to do necessary interviews to decide whether the candidate is the ideal candidate.';

const row = (category, name, score) => ({
  category,
  assessment_name: name,
  score,
  performance_summary: `${name} summary sentence.`,
});

const BASE = {
  candidate_id: '00000000-0000-0000-0000-000000000001',
  company_name: 'Acme Holdings',
  company_logo_url: 'https://cdn.example.com/acme.png',
  candidate_full_name: 'Jane Doe',
  candidate_email: 'jane@example.com',
  target_role: 'Analyst',
  completed_at: '2026-10-01T10:00:00Z',
  synthesis_status: 'ok',
  total_assessments_completed: 3,
  category_averages: { Cognitive: 82.5, Personality: 64 },
  executive_summary: 'Strong analytical candidate.',
  strengths: ['Fast numerical reasoning.'],
  areas_to_explore: ['May over-index on detail.'],
  competency_breakdown: [
    row('Personality', 'Work Style Inventory', 64),
    row('Cognitive', 'Numerical Reasoning', 90),
    row('Cognitive', 'Verbal Reasoning', 75),
  ],
  category_summaries: [
    { category: 'Cognitive', summary: 'Strong reasoning across both cognitive tests.' },
    { category: 'Personality', summary: 'Steady work style overall.' },
    { category: 'Technical', summary: 'Must never render as a pillar summary.' },
  ],
  custom_questions: [],
};

describe('report copy', () => {
  it('matches the contractual footer and disclaimer text exactly', () => {
    expect(FOOTER_ENTITY).toBe('MindQ (Pvt.) Ltd.');
    expect(`${FOOTER_NOTICE_PREFIX}${FOOTER_ENTITY}`).toBe(SPEC_FOOTER);
    expect(FOOTER_NOTICE).toBe(SPEC_FOOTER);
    expect(FIT_DISCLAIMER).toBe(SPEC_FIT_DISCLAIMER);
  });
});

describe('MindQReport', () => {
  it('renders nothing without data', () => {
    const { container } = render(<MindQReport data={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('puts the MindQ mark left and the client logo right in the header', () => {
    const { container } = render(<MindQReport data={BASE} />);
    const top = container.querySelector('.mq-header-top');
    const [left, right] = top.children;
    expect(left).toHaveAttribute('aria-label', 'MindQ');
    expect(within(right).getByAltText('Acme Holdings logo')).toHaveAttribute(
      'src',
      'https://cdn.example.com/acme.png',
    );
  });

  it('shows candidate name, target role, email, and assessments completed', () => {
    const { container } = render(<MindQReport data={BASE} />);
    expect(screen.getByText(REPORT_TITLE)).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Jane Doe' })).toBeInTheDocument();
    const meta = container.querySelector('.mq-meta-grid');
    expect(within(meta).getByText('Analyst')).toBeInTheDocument();
    expect(within(meta).getByText('jane@example.com')).toBeInTheDocument();
    expect(within(meta).getByText('Assessments completed').nextSibling).toHaveTextContent('3');
  });

  it('renders the footer with the MindQ mark and both disclaimers', () => {
    const { container } = render(<MindQReport data={BASE} />);
    const footer = container.querySelector('[data-pdf-footer]');
    expect(within(footer).getByLabelText('MindQ')).toBeInTheDocument();
    const notice = footer.querySelector('.mq-footer-text:not(.mq-footer-disclaimer)');
    expect(notice?.textContent).toBe(SPEC_FOOTER);
    expect(within(footer).getByText(SPEC_FIT_DISCLAIMER)).toBeInTheDocument();
    const entity = footer.querySelector('.mq-entity');
    expect(entity).toHaveTextContent('MindQ (Pvt.) Ltd.');
    expect(entity).toHaveClass('mq-entity');
  });

  it('hides a redundant Personal Initiative subscale row', () => {
    const { container } = render(
      <MindQReport
        data={{
          ...BASE,
          total_assessments_completed: 1,
          competency_breakdown: [
            {
              category: 'Personality',
              assessment_name: 'Personal Initiative Scale',
              score: 78,
              performance_summary: 'Shows strong self-starting behaviour.',
              subscales: [
                {
                  name: 'Personal Initiative',
                  mean: 4.2,
                  position_pct: 78,
                  band_label: 'High',
                },
              ],
            },
          ],
        }}
      />,
    );
    expect(screen.getByText('Personal Initiative Scale')).toBeInTheDocument();
    expect(container.querySelector('.mq-subscale-row')).toBeNull();
  });

  it('does not render unlike-test pillar average cards', () => {
    render(<MindQReport data={BASE} />);
    expect(screen.queryByRole('region', { name: 'Category scores' })).not.toBeInTheDocument();
    expect(screen.queryByText('82.5%')).not.toBeInTheDocument();
  });

  it('never renders AI, fit, MCQ, or recommendation copy even if the payload carries them', () => {
    const { container } = render(
      <MindQReport
        data={{
          ...BASE,
          overall_fit: 91,
          mcq_score: 70,
          recommendation_label: 'Strong Hire',
          custom_questions: [{ id: 'q1', prompt: 'Explain X', ai_eval_status: 'failed' }],
        }}
      />,
    );
    const text = container.textContent;
    expect(text).not.toMatch(/\bAI\b|Gemini|Candidate Fit|Overall Fit|MCQ Score|Strong Hire|Recommendation/);
  });

  it('groups the breakdown under category headers in canonical order', () => {
    render(<MindQReport data={BASE} />);
    const groups = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent);
    expect(groups).toEqual(['Cognitive', 'Personality']);

    const cognitive = screen.getByRole('heading', { name: 'Cognitive' }).closest('article');
    const items = within(cognitive).getAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(within(items[0]).getByText('Numerical Reasoning')).toBeInTheDocument();
    expect(within(items[0]).getByText('90%')).toBeInTheDocument();
    expect(within(items[0]).getByText('Numerical Reasoning summary sentence.')).toBeInTheDocument();
    expect(items[0].querySelector('.mq-bar-fill')).toHaveStyle({ width: '90%' });
    expect(items[0].querySelector('.mq-score-value')).toHaveClass('mq-score-value');
  });

  it('renders every Mini-IPIP subscale from score_details including Extraversion', () => {
    render(
      <MindQReport
        data={{
          ...BASE,
          competency_breakdown: [
            {
              category: 'Personality',
              assessment_name: 'Mini-IPIP',
              score: null,
              display_score: null,
              band: null,
              score_kind: 'traits',
              performance_summary: 'Trait profile recorded.',
              subscales: [
                { name: 'Surgency or Extraversion', mean: 3, position_pct: 50, band_label: 'Moderate' },
                { name: 'Agreeableness', mean: 3, position_pct: 50, band_label: 'Moderate' },
                { name: 'Conscientiousness', mean: 3, position_pct: 50, band_label: 'Moderate' },
                { name: 'Neuroticism', mean: 3, position_pct: 50, band_label: 'Moderate' },
                { name: 'Intellect or Imagination', mean: 2.5, position_pct: 37.5, band_label: 'Low' },
              ],
            },
          ],
        }}
      />,
    );
    const mini = screen.getByRole('heading', { name: 'Personality' }).closest('article');
    expect(within(mini).getByText('Surgency or Extraversion')).toBeInTheDocument();
    expect(within(mini).getByText('Neuroticism')).toBeInTheDocument();
    expect(within(mini).getAllByText(/Moderate|Low/).length).toBeGreaterThanOrEqual(5);
  });

  it('keeps instrument score and band labels on one nowrap badge line', () => {
    const { container } = render(
      <MindQReport
        data={{
          ...BASE,
          competency_breakdown: [
            {
              category: 'Personality',
              assessment_name: 'Work Style Inventory',
              score: null,
              display_score: '100',
              band: 'Very high',
              performance_summary: 'Elevated drive.',
              subscales: [
                {
                  name: 'Reflective',
                  mean: 2,
                  position_pct: null,
                  band_label: 'Mostly reflective',
                },
              ],
            },
            {
              category: 'Behavioral',
              assessment_name: 'CRT',
              score: null,
              display_score: '2 of 3',
              band: 'Mostly reflective',
              performance_summary: 'Mostly reflective answers.',
            },
            {
              category: 'Behavioral',
              assessment_name: 'SJT',
              score: null,
              display_score: '16/24',
              band: 'Generally sound',
              performance_summary: 'Generally sound judgment.',
            },
          ],
        }}
      />,
    );
    expect(screen.getByText('100 · Very high')).toBeInTheDocument();
    expect(screen.getByText('2 of 3 · Mostly reflective')).toBeInTheDocument();
    expect(screen.getByText('16/24 · Generally sound')).toBeInTheDocument();
    container.querySelectorAll('.mq-score-value').forEach((badge) => {
      expect(badge.textContent).not.toMatch(/\n/);
      expect(badge.textContent.trim().length).toBeGreaterThan(0);
    });
    expect(container.querySelector('.mq-subscale-value')).toHaveTextContent('Mostly reflective');
    expect(container.querySelector('[data-pdf-print-only]')).toBeTruthy();
  });

  it('renders pillar summaries for psychometric categories only', () => {
    const { container } = render(<MindQReport data={BASE} />);
    const cognitive = screen.getByRole('heading', { name: 'Cognitive' }).closest('article');
    expect(within(cognitive).getByText('Strong reasoning across both cognitive tests.')).toBeInTheDocument();
    expect(cognitive.querySelector('.mq-group-summary')).toHaveTextContent(
      'Strong reasoning across both cognitive tests.',
    );
    const personality = screen.getByRole('heading', { name: 'Personality' }).closest('article');
    expect(within(personality).getByText('Steady work style overall.')).toBeInTheDocument();
    expect(container.textContent).not.toContain('Must never render as a pillar summary.');
  });

  it('renders unchanged when category_summaries is absent or malformed', () => {
    const { container, rerender } = render(
      <MindQReport data={{ ...BASE, category_summaries: undefined }} />,
    );
    expect(container.querySelectorAll('.mq-group-summary')).toHaveLength(0);
    rerender(
      <MindQReport
        data={{ ...BASE, category_summaries: [null, { category: 'Cognitive' }, { summary: 'x' }] }}
      />,
    );
    expect(container.querySelectorAll('.mq-group-summary')).toHaveLength(0);
  });

  it('marks each major section as a keep-together block for print and PDF', () => {
    const { container } = render(<MindQReport data={BASE} />);
    const first = container.querySelector('.mq-first-page');
    expect(first).toHaveAttribute('data-pdf-block');
    expect(first).toHaveClass('break-inside-avoid', 'print:break-inside-avoid', 'print:break-after-auto');
    expect(within(first).getByRole('heading', { name: 'Executive Summary' })).toBeInTheDocument();
    expect(within(first).queryByRole('region', { name: 'Category scores' })).not.toBeInTheDocument();

    container.querySelectorAll('article.mq-group').forEach((group) => {
      expect(group).toHaveAttribute('data-pdf-block');
      expect(group).toHaveClass('break-inside-avoid');
    });
    expect(container.querySelector('.mq-strengths-risks')).toHaveAttribute('data-pdf-block');
    expect(container.querySelectorAll('[data-pdf-row]')).toHaveLength(3);
  });

  it('keeps the breakdown title attached to the first group', () => {
    render(<MindQReport data={BASE} />);
    const title = screen.getByRole('heading', { name: 'Competency Breakdown' });
    const wrapper = title.parentElement;
    expect(wrapper).toHaveAttribute('data-pdf-block');
    expect(within(wrapper).getByRole('heading', { name: 'Cognitive' })).toBeInTheDocument();
  });

  it.each([3, 6])('renders every completed test when the candidate took %i tests', (count) => {
    const categories = ['Cognitive', 'Personality', 'Behavioral', 'Technical'];
    const breakdown = Array.from({ length: count }, (_, i) =>
      row(categories[i % 4], `Test ${i + 1}`, 50 + i),
    );
    const { container } = render(
      <MindQReport data={{ ...BASE, competency_breakdown: breakdown }} />,
    );
    expect(container.querySelectorAll('[data-pdf-row]')).toHaveLength(count);
    expect(container.querySelectorAll('article.mq-group')).toHaveLength(Math.min(count, 4));
  });

  it('renders strengths and areas to explore', () => {
    render(<MindQReport data={BASE} />);
    expect(screen.getByText('Fast numerical reasoning.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Areas to explore' })).toBeInTheDocument();
    expect(screen.getByText('May over-index on detail.')).toBeInTheDocument();
  });

  it('renders Strengths and Areas to Explore as bulleted lists', () => {
    const { container } = render(
      <MindQReport
        data={{
          ...BASE,
          strengths: ['One', 'Two', 'Three', 'Four', 'Five'],
          areas_to_explore: ['A', 'B', 'C', 'D', 'E'],
        }}
      />,
    );
    const strengths = container.querySelector('.strengths-block ul');
    const areas = container.querySelector('.areas-block ul');
    expect(strengths).toBeTruthy();
    expect(areas).toBeTruthy();
    expect(strengths.querySelectorAll('li')).toHaveLength(5);
    expect(areas.querySelectorAll('li')).toHaveLength(5);
    expect(container.querySelector('.list-section')).toBeTruthy();
  });

  it('renders timed-out modules and aligns the assessments completed count', () => {
    const { container } = render(
      <MindQReport
        data={{
          ...BASE,
          total_assessments_completed: 99,
          competency_breakdown: [
            row('Cognitive', 'Numerical Reasoning', 90),
            {
              category: 'Cognitive',
              assessment_name: 'Verbal Reasoning',
              score: null,
              display_score: 'Incomplete',
              band: 'Timed Out / Incomplete',
              status: 'TIMED_OUT',
              timed_out: true,
              status_note:
                'Candidate ran out of time before completing all items. Displayed score reflects attempted responses only.',
              performance_summary: 'Timed out after answering 2 of 10 items.',
            },
          ],
        }}
      />,
    );
    expect(within(container.querySelector('.mq-meta-grid')).getByText('2')).toBeInTheDocument();
    expect(screen.getByText('Verbal Reasoning')).toBeInTheDocument();
    expect(screen.getAllByText('Timed Out / Incomplete').length).toBeGreaterThan(0);
    expect(
      screen.getByText(/Candidate ran out of time before completing all items/i),
    ).toBeInTheDocument();
  });

  it('shows a retry message when the summary failed', () => {
    render(
      <MindQReport
        data={{ ...BASE, executive_summary: '', strengths: [], synthesis_status: 'failed' }}
      />,
    );
    expect(screen.getByText(/executive summary could not be completed/i)).toBeInTheDocument();
    expect(screen.getByText('No strengths recorded yet.')).toBeInTheDocument();
  });

  it('explains a skipped summary', () => {
    render(<MindQReport data={{ ...BASE, executive_summary: '', synthesis_status: 'skipped' }} />);
    expect(screen.getByText(/needs a target role/)).toBeInTheDocument();
  });

  describe('while the narrative is generating', () => {
    const GENERATING = {
      ...BASE,
      executive_summary: '',
      strengths: [],
      areas_to_explore: [],
      synthesis_status: 'generating',
    };

    it('shows shimmer placeholders for AI sections and keeps scores visible', () => {
      const { container } = render(<MindQReport data={GENERATING} narrativeLoading />);
      expect(screen.getByRole('status', { name: 'Generating executive summary' })).toBeInTheDocument();
      expect(screen.getByRole('status', { name: 'Generating strengths' })).toBeInTheDocument();
      expect(screen.getByRole('status', { name: 'Generating areas to explore' })).toBeInTheDocument();
      expect(screen.queryByText('No strengths recorded yet.')).not.toBeInTheDocument();
      expect(container.querySelectorAll('.mq-score-item').length).toBeGreaterThan(0);
    });

    it('renders static copy instead of a shimmer when not polling (PDF export)', () => {
      const { container } = render(<MindQReport data={GENERATING} />);
      expect(container.querySelector('.mq-skeleton')).toBeNull();
      expect(screen.getByText(/still being generated/i)).toBeInTheDocument();
      expect(screen.getByText('No strengths recorded yet.')).toBeInTheDocument();
    });

    it('prefers real narrative text over the shimmer', () => {
      render(<MindQReport data={{ ...BASE, synthesis_status: 'ok' }} narrativeLoading />);
      expect(screen.getByText('Strong analytical candidate.')).toBeInTheDocument();
      expect(screen.queryByRole('status', { name: 'Generating executive summary' })).toBeNull();
    });
  });

  it('drops malformed breakdown rows instead of crashing', () => {
    render(
      <MindQReport
        data={{
          ...BASE,
          competency_breakdown: [
            null,
            { category: 'Technical', assessment_name: '', score: 50 },
            { category: 'Technical', assessment_name: 'SQL', score: 'n/a' },
            { category: 'Technical', assessment_name: 'Python', score: '72.5' },
          ],
        }}
      />,
    );
    const technical = screen.getByRole('heading', { name: 'Technical' }).closest('article');
    expect(within(technical).getByText('Python')).toBeInTheDocument();
    expect(within(technical).queryByText('SQL')).not.toBeInTheDocument();
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

  it('handles a candidate with no completed assessments', () => {
    render(
      <MindQReport
        data={{
          ...BASE,
          total_assessments_completed: 0,
          category_averages: {},
          competency_breakdown: [],
        }}
      />,
    );
    expect(screen.getByText('Competency scores are not available yet.')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Category scores' })).not.toBeInTheDocument();
    expect(screen.queryByText('N/A')).not.toBeInTheDocument();
  });
});
