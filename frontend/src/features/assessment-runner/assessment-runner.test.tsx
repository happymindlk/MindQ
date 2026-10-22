import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { RunnerTest } from '../assessment-builder/api/library-api';
import { AssessmentRunner } from './assessment-runner';

const TRANSPORT = {
  autosave: vi.fn(async () => undefined),
  submit: vi.fn(async () => undefined),
};

function test(overrides: Partial<RunnerTest['questions'][number]> = {}): RunnerTest {
  return {
    id: 'test-1',
    title: 'Personality',
    description: null,
    time_limit_minutes: null,
    duration_seconds: null,
    timer_mode: 'flexible',
    shuffle_questions: false,
    started_at: null,
    answers: {},
    questions: [
      {
        id: 'q1',
        text: 'I plan ahead',
        type: 'likert',
        options: [],
        allow_multiple: false,
        media_url: null,
        likert_label_1: null,
        likert_label_5: null,
        ...overrides,
      },
    ],
  };
}

describe('AssessmentRunner question disclaimer', () => {
  it('renders the configured disclaimer above the question', () => {
    render(
      <AssessmentRunner
        test={test({ show_disclaimer: true, disclaimer_text: 'Answer from your own perspective.' })}
        mode="preview"
        initialAnswers={{}}
        transport={TRANSPORT}
        onSubmitted={() => undefined}
        onLocked={() => undefined}
        onExit={() => undefined}
      />,
    );
    const note = screen.getByRole('note');
    expect(note).toHaveTextContent('Answer from your own perspective.');
    const prompt = screen.getByText('I plan ahead');
    expect(note.compareDocumentPosition(prompt) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('renders no disclaimer when the flag is off', () => {
    render(
      <AssessmentRunner
        test={test({ show_disclaimer: false, disclaimer_text: 'Answer from your own perspective.' })}
        mode="preview"
        initialAnswers={{}}
        transport={TRANSPORT}
        onSubmitted={() => undefined}
        onLocked={() => undefined}
        onExit={() => undefined}
      />,
    );
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
  });
});
