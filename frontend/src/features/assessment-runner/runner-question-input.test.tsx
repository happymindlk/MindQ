import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { RunnerQuestion } from '../assessment-builder/api/library-api';
import { RunnerQuestionInput } from './runner-question-input';

function likert(overrides: Partial<RunnerQuestion> = {}): RunnerQuestion {
  return {
    id: 'l1',
    text: 'I plan ahead',
    type: 'likert',
    options: [],
    allow_multiple: false,
    media_url: null,
    likert_label_1: null,
    likert_label_5: null,
    ...overrides,
  };
}

describe('RunnerQuestionInput likert', () => {
  it('renders all five custom labels and emits the 1-based index, not the label', async () => {
    const onChange = vi.fn();
    const labels = ['Never', 'Rarely', 'Sometimes', 'Often', 'Always'];
    render(<RunnerQuestionInput question={likert({ scale_labels: labels })} value={undefined} disabled={false} onChange={onChange} />);
    for (const label of labels) expect(screen.getByText(label)).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('radio', { name: /often/i }));
    expect(onChange).toHaveBeenCalledWith(4);
  });

  it('falls back to IPIP anchors when the item carries no labels', () => {
    render(<RunnerQuestionInput question={likert()} value={3} disabled={false} onChange={() => undefined} />);
    expect(screen.getByRole('radio', { name: '1 of 5: Very Inaccurate' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: '3 of 5: Neither Inaccurate nor Accurate' })).toHaveAttribute(
      'aria-checked',
      'true',
    );
  });

  it('builds a full agreement scale from legacy endpoint labels', () => {
    render(
      <RunnerQuestionInput
        question={likert({ likert_label_1: 'Strongly Disagree', likert_label_5: 'Strongly Agree' })}
        value={undefined}
        disabled
        onChange={() => undefined}
      />,
    );
    expect(screen.getByText('Neutral')).toBeInTheDocument();
    expect(screen.getAllByRole('radio').every((r) => (r as HTMLButtonElement).disabled)).toBe(true);
  });
});
