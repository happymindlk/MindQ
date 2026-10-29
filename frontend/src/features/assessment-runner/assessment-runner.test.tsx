import { createEvent, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { RunnerTest } from '../assessment-builder/api/library-api';
import {
  DEFAULT_CONFIDENTIALITY_NOTICE_TEXT,
  DEFAULT_TOP_DISCLAIMER_TEXT,
} from '../assessment-builder/types/module';
import type { AnswerValue } from '../assessment-builder/types/telemetry';
import { AssessmentRunner, type RunnerTransport } from './assessment-runner';

const TRANSPORT = {
  autosave: vi.fn(async () => undefined),
  submit: vi.fn(async () => undefined),
};

function test(
  overrides: Partial<RunnerTest['questions'][number]> = {},
  moduleKind: RunnerTest['module_kind'] = 'psychometric',
  testOverrides: Partial<RunnerTest> = {},
): RunnerTest {
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
    ...testOverrides,
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

function renderRunner(
  runnerTest: RunnerTest,
  transport: RunnerTransport = TRANSPORT,
  mode: 'live' | 'preview' = 'preview',
  callbacks: {
    onSubmitted?: () => void;
    onTimeExpired?: () => void;
    onLocked?: (message: string) => void;
    onExit?: () => void;
    initialAnswers?: Record<string, AnswerValue>;
  } = {},
) {
  return render(
    <AssessmentRunner
      test={runnerTest}
      mode={mode}
      initialAnswers={callbacks.initialAnswers ?? {}}
      transport={transport}
      onSubmitted={callbacks.onSubmitted ?? (() => undefined)}
      onTimeExpired={callbacks.onTimeExpired}
      onLocked={callbacks.onLocked ?? (() => undefined)}
      onExit={callbacks.onExit ?? (() => undefined)}
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

describe('AssessmentRunner module top disclaimer', () => {
  it('renders the module disclaimer above the prompt on every question', async () => {
    const base = twoQuestionTest('psychometric');
    renderRunner(
      {
        ...base,
        show_top_disclaimer: true,
        top_disclaimer_text: DEFAULT_TOP_DISCLAIMER_TEXT,
      },
      TRANSPORT,
      'preview',
    );
    const note = screen
      .getAllByRole('note')
      .find((el) => el.textContent?.includes('no right or wrong answers'));
    expect(note).toBeTruthy();
    const prompt = screen.getByText('First question');
    expect(note!.compareDocumentPosition(prompt) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    const user = userEvent.setup();
    await user.click(screen.getByRole('radio', { name: /Alpha/ }));
    await user.click(screen.getByRole('button', { name: /Next question/ }));
    expect(screen.getByText('Second question')).toBeInTheDocument();
    expect(screen.getByText(/no right or wrong answers/)).toBeInTheDocument();
  });

  it('renders no module disclaimer when the flag is off', () => {
    renderRunner(
      test({}, 'psychometric', {
        show_top_disclaimer: false,
        top_disclaimer_text: DEFAULT_TOP_DISCLAIMER_TEXT,
      }),
    );
    expect(screen.queryByText(/no right or wrong answers/)).not.toBeInTheDocument();
  });

  it('coexists with a per-question disclaimer, module notice first', () => {
    renderRunner(
      test(
        { show_disclaimer: true, disclaimer_text: 'Per-question note.' },
        'psychometric',
        { show_top_disclaimer: true, top_disclaimer_text: 'Module-wide note.' },
      ),
    );
    const notes = screen.getAllByRole('note').map((el) => el.textContent);
    expect(notes[0]).toContain('Module-wide note.');
    expect(notes[1]).toContain('Per-question note.');
  });
});

describe('AssessmentRunner psychometric integrity notice', () => {
  it('renders the configured bold italic notice beneath the options', () => {
    const base = twoQuestionTest('psychometric');
    renderRunner({
      ...base,
      show_confidentiality_notice: true,
      confidentiality_notice_text: DEFAULT_CONFIDENTIALITY_NOTICE_TEXT,
    });
    const notice = screen.getByText(/CONFIDENTIALITY & INTEGRITY NOTICE/);
    expect(notice.className).toContain('font-bold');
    expect(notice.className).toContain('italic');
    expect(notice).toHaveTextContent(
      'This assessment is monitored for unauthorized AI assistance, automated inputs, and screen capture. Copying, reproducing, or sharing these questions is strictly prohibited. Violations will result in immediate test invalidation and reporting to the hiring organization.',
    );
    expect(notice.textContent).not.toContain('***');
    const option = screen.getByRole('radio', { name: /Alpha/ });
    expect(option.compareDocumentPosition(notice) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('renders a custom confidentiality text when configured', () => {
    const base = twoQuestionTest('psychometric');
    renderRunner({
      ...base,
      show_confidentiality_notice: true,
      confidentiality_notice_text: 'Custom integrity wording.',
    });
    expect(screen.getByText('Custom integrity wording.')).toBeInTheDocument();
  });

  it('does not render the notice when the flag is off, even for psychometric modules', () => {
    const base = twoQuestionTest('psychometric');
    renderRunner({
      ...base,
      show_confidentiality_notice: false,
      confidentiality_notice_text: DEFAULT_CONFIDENTIALITY_NOTICE_TEXT,
    });
    expect(screen.queryByText(/CONFIDENTIALITY & INTEGRITY NOTICE/)).not.toBeInTheDocument();
  });

  it('does not render the notice for technical modules without it enabled', () => {
    renderRunner(twoQuestionTest('technical'));
    expect(screen.queryByText(/CONFIDENTIALITY & INTEGRITY NOTICE/)).not.toBeInTheDocument();
  });
});

describe('AssessmentRunner timer tone', () => {
  it('shows the amber caution tone in the middle third of an 18-minute test', () => {
    const startedAt = new Date(Date.now() - 600_000).toISOString();
    renderRunner(
      test({}, 'psychometric', {
        duration_seconds: 1080,
        timer_mode: 'strict',
        started_at: startedAt,
      }),
    );
    const badge = screen.getByRole('timer');
    expect(badge).toHaveAttribute('data-tone', 'caution');
    expect(badge.className).toContain('text-warning');
  });

  it('shows the green safe tone while more than two-thirds remains', () => {
    const startedAt = new Date(Date.now() - 60_000).toISOString();
    renderRunner(
      test({}, 'psychometric', {
        duration_seconds: 1080,
        timer_mode: 'strict',
        started_at: startedAt,
      }),
    );
    const badge = screen.getByRole('timer');
    expect(badge).toHaveAttribute('data-tone', 'safe');
    expect(badge.className).toContain('text-success');
  });
});

describe('AssessmentRunner strict expiry', () => {
  function expiredTest(): RunnerTest {
    return {
      ...twoQuestionTest('psychometric'),
      duration_seconds: 60,
      timer_mode: 'strict',
      started_at: new Date(Date.now() - 61_000).toISOString(),
    };
  }

  it('disables inputs, flush-submits current answers, and calls onTimeExpired on success', async () => {
    const transport = {
      autosave: vi.fn(async () => undefined),
      submit: vi.fn(async () => undefined),
    };
    const onSubmitted = vi.fn();
    const onTimeExpired = vi.fn();
    renderRunner(expiredTest(), transport, 'live', {
      onSubmitted,
      onTimeExpired,
      initialAnswers: { q1: 'Alpha' },
    });

    await waitFor(() => expect(onTimeExpired).toHaveBeenCalledTimes(1));
    expect(onSubmitted).not.toHaveBeenCalled();
    expect(transport.submit).toHaveBeenCalledTimes(1);
    expect(transport.submit).toHaveBeenCalledWith(
      expect.objectContaining({
        responses: [
          expect.objectContaining({ question_id: 'q1', response: { answer: 'Alpha' } }),
        ],
      }),
    );
    expect(screen.getByRole('radio', { name: /Alpha/ })).toBeDisabled();
    expect(await screen.findByText(/Time is up/)).toBeInTheDocument();
  });

  it('keeps the retry banner and does not navigate when the expiry submit fails', async () => {
    const transport = {
      autosave: vi.fn(async () => undefined),
      submit: vi.fn(async () => {
        throw new Error('network down');
      }),
    };
    const onSubmitted = vi.fn();
    const onTimeExpired = vi.fn();
    renderRunner(expiredTest(), transport, 'live', { onSubmitted, onTimeExpired });

    expect(await screen.findByText(/Time is up/)).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: /Retry submit/ })).toBeInTheDocument();
    expect(onTimeExpired).not.toHaveBeenCalled();
    expect(onSubmitted).not.toHaveBeenCalled();
    expect(screen.getByRole('radio', { name: /Alpha/ })).toBeDisabled();
  });

  it('falls back to onSubmitted when onTimeExpired is not provided (preview)', async () => {
    const transport = {
      autosave: vi.fn(async () => undefined),
      submit: vi.fn(async () => undefined),
    };
    const onSubmitted = vi.fn();
    renderRunner(expiredTest(), transport, 'preview', { onSubmitted });
    await waitFor(() => expect(onSubmitted).toHaveBeenCalledTimes(1));
  });
});

describe('AssessmentRunner flexible overtime', () => {
  it('does not auto-submit when a flexible timer runs over', async () => {
    const transport = {
      autosave: vi.fn(async () => undefined),
      submit: vi.fn(async () => undefined),
    };
    const onSubmitted = vi.fn();
    const onTimeExpired = vi.fn();
    renderRunner(
      {
        ...twoQuestionTest('psychometric'),
        duration_seconds: 60,
        timer_mode: 'flexible',
        started_at: new Date(Date.now() - 61_000).toISOString(),
      },
      transport,
      'live',
      { onSubmitted, onTimeExpired },
    );
    await screen.findByRole('timer');
    expect(transport.submit).not.toHaveBeenCalled();
    expect(onTimeExpired).not.toHaveBeenCalled();
    expect(onSubmitted).not.toHaveBeenCalled();
  });
});

describe('AssessmentRunner autosave race', () => {
  it('posts the latest answer after an in-flight save for the same item id', async () => {
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
    expect(transport.autosave).toHaveBeenCalledTimes(1);
    expect(transport.autosave).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({ question_id: 'q1' }),
    );

    await user.click(screen.getByRole('button', { name: /Previous/ }));
    await user.click(screen.getByRole('radio', { name: /Beta/ }));
    await user.click(screen.getByRole('button', { name: /Next question/ }));

    resolveSave?.();
    await waitFor(() => expect(transport.autosave).toHaveBeenCalledTimes(2));
    expect(transport.autosave).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        question_id: 'q1',
        response: { answer: 'Beta' },
      }),
    );
  });
});

describe('AssessmentRunner content protection', () => {
  it('disables text selection and blocks copy/cut/context menu on the question card', () => {
    const { container } = renderRunner(test());
    const section = container.querySelector('section');
    expect(section).toBeTruthy();
    expect(section!.className).toContain('select-none');

    for (const type of ['copy', 'cut', 'contextMenu'] as const) {
      const event = createEvent[type](section!);
      fireEvent(section!, event);
      expect(event.defaultPrevented).toBe(true);
    }
  });
});

describe('AssessmentRunner media URLs', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('rewrites localhost assessment-media URLs for the figure img src', () => {
    vi.stubEnv('VITE_SUPABASE_URL', 'https://proj.supabase.co');
    renderRunner(
      test({
        media_url:
          'http://127.0.0.1:54321/storage/v1/object/public/assessment-media/modules/m1/figure.png',
      }),
    );
    const img = screen.getByRole('img', { name: /figure for question 1/i });
    expect(img).toHaveAttribute(
      'src',
      'https://proj.supabase.co/storage/v1/object/public/assessment-media/modules/m1/figure.png',
    );
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

  it('exits without waiting for a pending autosave flush', async () => {
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
    const onExit = vi.fn();
    const user = userEvent.setup();
    renderRunner(twoQuestionTest(), transport, 'live', { onExit });

    await user.click(screen.getByRole('radio', { name: /Alpha/ }));
    await user.click(screen.getByRole('button', { name: /Back to dashboard/i }));
    expect(onExit).toHaveBeenCalledTimes(1);
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
