import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { RunnerTest } from '../assessment-builder/api/library-api';
import { AssessmentRunner, type RunnerTransport } from './assessment-runner';

const TRANSPORT = {
  autosave: vi.fn(async () => undefined),
  submit: vi.fn(async () => undefined),
};

function test(overrides: Partial<RunnerTest['questions'][number]> = {}, moduleKind: RunnerTest['module_kind'] = 'psychometric'): RunnerTest {
  return {
    id: 'test-1',
    title: 'Personality',
    description: null,
    module_kind: moduleKind,
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

function twoQuestionTest(moduleKind: RunnerTest['module_kind'] = 'psychometric'): RunnerTest {
  const base = test({}, moduleKind);
  return {
    ...base,
    questions: [
      {
        id: 'q1',
        text: 'First question',
        type: 'mcq',
        options: ['Alpha', 'Beta'],
        allow_multiple: false,
        media_url: null,
        likert_label_1: null,
        likert_label_5: null,
      },
      {
        id: 'q2',
        text: 'Second question',
        type: 'mcq',
        options: ['Gamma', 'Delta'],
        allow_multiple: false,
        media_url: null,
        likert_label_1: null,
        likert_label_5: null,
      },
    ],
  };
}

function renderRunner(runnerTest: RunnerTest, transport: RunnerTransport = TRANSPORT, mode: 'live' | 'preview' = 'preview') {
  return render(
    <AssessmentRunner
      test={runnerTest}
      mode={mode}
      initialAnswers={{}}
      transport={transport}
      onSubmitted={() => undefined}
      onLocked={() => undefined}
      onExit={() => undefined}
    />,
  );
}

describe('AssessmentRunner question disclaimer', () => {
  it('renders the configured disclaimer above the question', () => {
    renderRunner(test({ show_disclaimer: true, disclaimer_text: 'Answer from your own perspective.' }, 'technical'));
    const notes = screen.getAllByRole('note');
    const note = notes.find((el) => el.textContent?.includes('Answer from your own perspective.'));
    expect(note).toBeTruthy();
    const prompt = screen.getByText('I plan ahead');
    expect(note!.compareDocumentPosition(prompt) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('renders no disclaimer when the flag is off', () => {
    renderRunner(test({ show_disclaimer: false, disclaimer_text: 'Answer from your own perspective.' }, 'technical'));
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
  });
});

describe('AssessmentRunner psychometric integrity notice', () => {
  it('renders the bold italic notice beneath the options for psychometric modules', () => {
    renderRunner(twoQuestionTest('psychometric'));
    const notice = screen.getByText(/CONFIDENTIALITY & INTEGRITY NOTICE/);
    expect(notice.className).toContain('font-bold');
    expect(notice.className).toContain('italic');
    expect(notice).toHaveTextContent(
      '***This assessment is monitored for unauthorized AI assistance, automated inputs, and screen capture. Copying, reproducing, or sharing these questions is strictly prohibited. Violations will result in immediate test invalidation and reporting to the hiring organization.***',
    );
    const option = screen.getByRole('radio', { name: /Alpha/ });
    expect(option.compareDocumentPosition(notice) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('does not render the notice for technical modules', () => {
    renderRunner(twoQuestionTest('technical'));
    expect(screen.queryByText(/CONFIDENTIALITY & INTEGRITY NOTICE/)).not.toBeInTheDocument();
  });
});

describe('AssessmentRunner optimistic navigation', () => {
  it('advances to the next question without waiting for a pending autosave', async () => {
    let resolveSave: (() => void) | undefined;
    const transport = {
      autosave: vi.fn(
        () =>
          new Promise<void>((resolve) => {
            resolveSave = resolve;
          }),
      ),
      submit: vi.fn(async () => undefined),
    };
    const user = userEvent.setup();
    renderRunner(twoQuestionTest(), transport, 'live');

    await user.click(screen.getByRole('radio', { name: /Alpha/ }));
    await user.click(screen.getByRole('button', { name: /Next question/ }));

    expect(screen.getByText('Second question')).toBeInTheDocument();
    expect(screen.getByText('Question 2 of 2')).toBeInTheDocument();
    expect(transport.autosave).toHaveBeenCalledTimes(1);
    resolveSave?.();
  });

  it('keeps a failed background save queued and retries it on the next navigation', async () => {
    const transport = {
      autosave: vi.fn(async () => undefined),
      submit: vi.fn(async () => undefined),
    };
    transport.autosave.mockRejectedValueOnce(new Error('network down'));
    const user = userEvent.setup();
    renderRunner(twoQuestionTest(), transport, 'live');

    await user.click(screen.getByRole('radio', { name: /Alpha/ }));
    await user.click(screen.getByRole('button', { name: /Next question/ }));
    expect(screen.getByText('Second question')).toBeInTheDocument();
    expect(await screen.findByText('Saved offline')).toBeInTheDocument();
    expect(transport.autosave).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: /Previous/ }));
    expect(screen.getByText('First question')).toBeInTheDocument();
    await waitFor(() => expect(transport.autosave).toHaveBeenCalledTimes(2));
  });
});
