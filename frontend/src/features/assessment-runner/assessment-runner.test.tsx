import { act, createEvent, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { RunnerTest } from '../assessment-builder/api/library-api';
import {
  DEFAULT_CONFIDENTIALITY_NOTICE_TEXT,
  DEFAULT_TOP_DISCLAIMER_TEXT,
} from '../assessment-builder/types/module';
import type { AnswerValue } from '../assessment-builder/types/telemetry';
import {
  ASSESSMENT_TIMEOUT_MESSAGE,
  AssessmentRunner,
  type RunnerTransport,
} from './assessment-runner';

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
  it('renders the configured notice as a subtle footer below Previous / Next', () => {
    const base = twoQuestionTest('psychometric');
    renderRunner({
      ...base,
      show_confidentiality_notice: true,
      confidentiality_notice_text: DEFAULT_CONFIDENTIALITY_NOTICE_TEXT,
    });
    const notice = screen.getByText(/CONFIDENTIALITY & INTEGRITY NOTICE/);
    expect(notice.className).toContain('text-xs');
    expect(notice.className).toContain('text-slate-400');
    expect(notice.className).toContain('font-bold');
    expect(notice.className).toContain('italic');
    expect(notice.className).toContain('text-left');
    expect(notice).toHaveTextContent(
      'This assessment is monitored for unauthorized AI assistance, automated inputs, and screen capture. Copying, reproducing, or sharing these questions is strictly prohibited. Violations will result in immediate test invalidation and reporting to the hiring organization.',
    );
    expect(notice.textContent).not.toContain('***');
    const next = screen.getByRole('button', { name: /Next question/ });
    expect(next.compareDocumentPosition(notice) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
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
    renderRunner(
      test({}, 'psychometric', {
        duration_seconds: 1080,
        timer_mode: 'strict',
        started_at: new Date(Date.now() - 600_000).toISOString(),
        remaining_seconds: 480,
      }),
    );
    const badge = screen.getByRole('timer');
    expect(badge).toHaveAttribute('data-tone', 'caution');
    expect(badge.className).toContain('text-warning');
  });

  it('shows the green safe tone while more than two-thirds remains', () => {
    renderRunner(
      test({}, 'psychometric', {
        duration_seconds: 1080,
        timer_mode: 'strict',
        started_at: new Date(Date.now() - 60_000).toISOString(),
        remaining_seconds: 1020,
      }),
    );
    const badge = screen.getByRole('timer');
    expect(badge).toHaveAttribute('data-tone', 'safe');
    expect(badge.className).toContain('text-success');
  });
});

describe('AssessmentRunner untimed mount', () => {
  it('never auto-submits when duration and expires_at are null', async () => {
    const transport = {
      autosave: vi.fn(async () => undefined),
      submit: vi.fn(async () => undefined),
    };
    const onTimeExpired = vi.fn();
    renderRunner(
      {
        ...twoQuestionTest('psychometric'),
        duration_seconds: null,
        timer_mode: 'flexible',
        started_at: new Date().toISOString(),
        expires_at: null,
        write_expires_at: null,
        remaining_seconds: null,
        write_remaining_seconds: null,
        server_now: new Date().toISOString(),
      },
      transport,
      'live',
      { onTimeExpired },
    );

    expect(screen.queryByRole('timer')).not.toBeInTheDocument();
    await act(async () => {
      await Promise.resolve();
    });
    expect(transport.submit).not.toHaveBeenCalled();
    expect(onTimeExpired).not.toHaveBeenCalled();
  });

  it('never auto-submits on remaining_seconds 0 when expires_at is missing (live)', async () => {
    const transport = {
      autosave: vi.fn(async () => undefined),
      submit: vi.fn(async () => undefined),
    };
    const onTimeExpired = vi.fn();
    renderRunner(
      {
        ...twoQuestionTest('psychometric'),
        duration_seconds: 60,
        timer_mode: 'strict',
        started_at: new Date(Date.now() - 61_000).toISOString(),
        expires_at: null,
        write_expires_at: null,
        remaining_seconds: 0,
        write_remaining_seconds: 0,
      },
      transport,
      'live',
      { onTimeExpired },
    );

    await act(async () => {
      await Promise.resolve();
    });
    expect(transport.submit).not.toHaveBeenCalled();
    expect(onTimeExpired).not.toHaveBeenCalled();
  });
});

describe('AssessmentRunner resume question index', () => {
  it('opens on the first unanswered question when earlier answers are hydrated', () => {
    renderRunner(twoQuestionTest(), TRANSPORT, 'live', {
      initialAnswers: { q1: 'Alpha' },
    });
    expect(screen.getByText('Second question')).toBeInTheDocument();
    expect(screen.getByText('Question 2 of 2')).toBeInTheDocument();
  });

  it('opens on the last question when every question already has an answer', () => {
    renderRunner(twoQuestionTest(), TRANSPORT, 'live', {
      initialAnswers: { q1: 'Alpha', q2: 'Beta' },
    });
    expect(screen.getByText('Second question')).toBeInTheDocument();
    expect(screen.getByText('Question 2 of 2')).toBeInTheDocument();
  });

  it('opens on question 1 when nothing is answered yet', () => {
    renderRunner(twoQuestionTest(), TRANSPORT, 'live');
    expect(screen.getByText('First question')).toBeInTheDocument();
    expect(screen.getByText('Question 1 of 2')).toBeInTheDocument();
  });
});

describe('AssessmentRunner leave / re-enter resume', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('resumes a 600s module at 04:00 from expires_at, ticks to 03:55, and does not autosave hydrated answers', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-11-13T12:06:00.000Z'));

    const transport = {
      autosave: vi.fn(async () => undefined),
      submit: vi.fn(async () => undefined),
    };
    const serverNow = '2026-11-13T12:06:00.000Z';
    const startedAt = '2026-11-13T12:00:00.000Z';
    const expiresAt = '2026-11-13T12:10:00.000Z'; // 240s remaining of 600s
    const writeExpiresAt = '2026-11-13T12:10:15.000Z';

    renderRunner(
      {
        ...twoQuestionTest('psychometric'),
        duration_seconds: 600,
        timer_mode: 'strict',
        started_at: startedAt,
        expires_at: expiresAt,
        write_expires_at: writeExpiresAt,
        server_now: serverNow,
        remaining_seconds: 240,
        write_remaining_seconds: 255,
        answers: { q1: 'Alpha' },
      },
      transport,
      'live',
      { initialAnswers: { q1: 'Alpha' } },
    );

    // Resume lands on the first unanswered question (q2) with timer intact.
    expect(screen.getByText('Question 2 of 2')).toBeInTheDocument();
    const badge = screen.getByRole('timer');
    expect(badge).toHaveTextContent('4:00');
    expect(badge).not.toHaveTextContent('10:00');

    // Hydrated answers must not fire an immediate autosave.
    await act(async () => {
      await Promise.resolve();
    });
    expect(transport.autosave).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(5_000);
    });
    expect(badge).toHaveTextContent('3:55');
    expect(transport.autosave).not.toHaveBeenCalled();
    expect(transport.submit).not.toHaveBeenCalled();
  });

  it('resumes from remaining_seconds alone without resetting to duration_seconds', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-11-13T12:06:00.000Z'));

    const transport = {
      autosave: vi.fn(async () => undefined),
      submit: vi.fn(async () => undefined),
    };

    renderRunner(
      {
        ...twoQuestionTest('psychometric'),
        duration_seconds: 600,
        timer_mode: 'strict',
        started_at: '2026-11-13T12:00:00.000Z',
        remaining_seconds: 240,
        write_remaining_seconds: 255,
      },
      transport,
      'live',
      { initialAnswers: { q1: 'Beta' } },
    );

    expect(screen.getByText('Question 2 of 2')).toBeInTheDocument();
    const badge = screen.getByRole('timer');
    expect(badge).toHaveTextContent('4:00');

    await act(async () => {
      vi.advanceTimersByTime(5_000);
    });
    expect(badge).toHaveTextContent('3:55');
    expect(transport.autosave).not.toHaveBeenCalled();
  });
});

describe('AssessmentRunner strict expiry', () => {
  function expiredTest(): RunnerTest {
    const now = Date.now();
    const started = new Date(now - 61_000);
    const expires = new Date(started.getTime() + 60_000); // 1s in the past
    return {
      ...twoQuestionTest('psychometric'),
      duration_seconds: 60,
      timer_mode: 'strict',
      started_at: started.toISOString(),
      expires_at: expires.toISOString(),
      // Write lock also elapsed so auto-submit arms immediately.
      write_expires_at: expires.toISOString(),
      server_now: new Date(now).toISOString(),
      remaining_seconds: 0,
      write_remaining_seconds: 0,
    };
  }

  it('auto-submits partial answers, hides the timer (no blinking 00:00), then shows the timeout screen', async () => {
    let resolveSubmit: (() => void) | undefined;
    const transport = {
      autosave: vi.fn(async () => undefined),
      submit: vi.fn(
        () =>
          new Promise<void>((resolve) => {
            resolveSubmit = resolve;
          }),
      ),
    };
    const onSubmitted = vi.fn();
    const onTimeExpired = vi.fn();
    const onExit = vi.fn();
    renderRunner(expiredTest(), transport, 'live', {
      onSubmitted,
      onTimeExpired,
      onExit,
      initialAnswers: { q1: 'Alpha' },
    });

    expect(await screen.findByRole('status', { name: 'Submitting...' })).toBeInTheDocument();
    expect(screen.queryByRole('timer')).not.toBeInTheDocument();
    expect(screen.queryByText(/0:00/)).not.toBeInTheDocument();
    expect(transport.submit).toHaveBeenCalledTimes(1);
    expect(transport.submit).toHaveBeenCalledWith(
      expect.objectContaining({
        responses: [
          expect.objectContaining({ question_id: 'q1', response: { answer: 'Alpha' } }),
        ],
      }),
    );

    resolveSubmit?.();
    await waitFor(() => expect(onTimeExpired).toHaveBeenCalledTimes(1));
    expect(onSubmitted).not.toHaveBeenCalled();
    expect(await screen.findByText(ASSESSMENT_TIMEOUT_MESSAGE)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Return to Dashboard' })).toBeInTheDocument();
    expect(screen.queryByRole('radio', { name: /Alpha/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('timer')).not.toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole('button', { name: 'Return to Dashboard' }));
    expect(onExit).toHaveBeenCalledTimes(1);
  });

  it('auto-submits when allAnswered on the last-question screen and shows the timeout view', async () => {
    let resolveSubmit: (() => void) | undefined;
    const transport = {
      autosave: vi.fn(async () => undefined),
      submit: vi.fn(
        () =>
          new Promise<void>((resolve) => {
            resolveSubmit = resolve;
          }),
      ),
    };
    const onSubmitted = vi.fn();
    const onTimeExpired = vi.fn();
    const onExit = vi.fn();
    // All answers → resume lands on the final question with "Submit test" visible.
    renderRunner(expiredTest(), transport, 'live', {
      onSubmitted,
      onTimeExpired,
      onExit,
      initialAnswers: { q1: 'Alpha', q2: 'Gamma' },
    });

    expect(await screen.findByRole('status', { name: 'Submitting...' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Submit test/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByRole('timer')).not.toBeInTheDocument();

    resolveSubmit?.();
    await waitFor(() => expect(onTimeExpired).toHaveBeenCalledTimes(1));
    expect(onSubmitted).not.toHaveBeenCalled();
    expect(transport.submit).toHaveBeenCalledTimes(1);
    expect(transport.submit).toHaveBeenCalledWith(
      expect.objectContaining({
        responses: expect.arrayContaining([
          expect.objectContaining({ question_id: 'q1', response: { answer: 'Alpha' } }),
          expect.objectContaining({ question_id: 'q2', response: { answer: 'Gamma' } }),
        ]),
      }),
    );
    expect(screen.getByText(ASSESSMENT_TIMEOUT_MESSAGE)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Return to Dashboard' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Submit test/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Confirm submit/i })).not.toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole('button', { name: 'Return to Dashboard' }));
    expect(onExit).toHaveBeenCalledTimes(1);
  });

  it('closes the all-answered confirm dialog at 00:00 and still shows the timeout screen', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let resolveSubmit: (() => void) | undefined;
    const transport = {
      autosave: vi.fn(async () => undefined),
      submit: vi.fn(
        () =>
          new Promise<void>((resolve) => {
            resolveSubmit = resolve;
          }),
      ),
    };
    const onSubmitted = vi.fn();
    const onTimeExpired = vi.fn();
    try {
      const startedAt = new Date('2026-11-13T12:00:00.000Z');
      vi.setSystemTime(startedAt);
      const expiresAt = new Date(startedAt.getTime() + 3_000);
      renderRunner(
        {
          ...twoQuestionTest('psychometric'),
          duration_seconds: 60,
          timer_mode: 'strict',
          started_at: startedAt.toISOString(),
          expires_at: expiresAt.toISOString(),
          write_expires_at: expiresAt.toISOString(),
          server_now: startedAt.toISOString(),
          remaining_seconds: 3,
          write_remaining_seconds: 3,
        },
        transport,
        'live',
        {
          onSubmitted,
          onTimeExpired,
          initialAnswers: { q1: 'Alpha', q2: 'Gamma' },
        },
      );

      expect(screen.getByText(/Question 2 of 2/)).toBeInTheDocument();
      // Fake timers pin performance.now() at 0; advance past the 300ms nav debounce.
      await act(async () => {
        vi.advanceTimersByTime(400);
      });
      fireEvent.click(screen.getByRole('button', { name: /Submit test/i }));
      expect(screen.getByRole('dialog')).toBeInTheDocument();
      expect(screen.getByText(/all complete/i)).toBeInTheDocument();

      await act(async () => {
        vi.setSystemTime(new Date(startedAt.getTime() + 4_000));
        vi.advanceTimersByTime(4_000);
      });

      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(screen.getByRole('status', { name: 'Submitting...' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /Submit test/i })).not.toBeInTheDocument();
      expect(transport.submit).toHaveBeenCalledTimes(1);

      resolveSubmit?.();
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(onTimeExpired).toHaveBeenCalledTimes(1);
      expect(onSubmitted).not.toHaveBeenCalled();
      expect(screen.getByText(ASSESSMENT_TIMEOUT_MESSAGE)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Return to Dashboard' })).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('cancels pending autosave and submits once at 00:00 without double-fire', async () => {
    vi.useFakeTimers();
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
    const onTimeExpired = vi.fn();
    try {
      const startedAt = new Date();
      const expiresAt = new Date(startedAt.getTime() + 3_000);
      renderRunner(
        {
          ...twoQuestionTest('psychometric'),
          duration_seconds: 60,
          timer_mode: 'strict',
          started_at: startedAt.toISOString(),
          expires_at: expiresAt.toISOString(),
          write_expires_at: expiresAt.toISOString(),
          server_now: startedAt.toISOString(),
          remaining_seconds: 3,
          write_remaining_seconds: 3,
        },
        transport,
        'live',
        { onTimeExpired },
      );

      fireEvent.click(screen.getByRole('radio', { name: /Alpha/ }));
      const visibilityDesc = Object.getOwnPropertyDescriptor(Document.prototype, 'visibilityState');
      Object.defineProperty(document, 'visibilityState', {
        configurable: true,
        get: () => 'hidden',
      });
      try {
        document.dispatchEvent(new Event('visibilitychange'));
        // autosave is invoked synchronously before its await; avoid waitFor under fake timers.
        expect(transport.autosave).toHaveBeenCalledTimes(1);

        await act(async () => {
          vi.advanceTimersByTime(4_000);
        });
        expect(transport.submit).toHaveBeenCalledTimes(1);
        expect(onTimeExpired).toHaveBeenCalledTimes(1);

        // Completing the in-flight autosave after cancel must not post again.
        resolveSave?.();
        await act(async () => {
          await Promise.resolve();
        });
        expect(transport.autosave).toHaveBeenCalledTimes(1);
        expect(transport.submit).toHaveBeenCalledTimes(1);
      } finally {
        if (visibilityDesc) {
          Object.defineProperty(Document.prototype, 'visibilityState', visibilityDesc);
        } else {
          Reflect.deleteProperty(document, 'visibilityState');
        }
      }
    } finally {
      vi.useRealTimers();
    }
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

describe('AssessmentRunner grace resume', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('does not instant-submit when display is 0 but write grace remains', async () => {
    vi.useFakeTimers();
    const transport = {
      autosave: vi.fn(async () => undefined),
      submit: vi.fn(async () => undefined),
    };
    const onTimeExpired = vi.fn();
    const now = Date.now();
    const startedAt = new Date(now - 61_000);
    const expiresAt = new Date(now - 1_000);
    const writeExpiresAt = new Date(now + 15_000);
    renderRunner(
      {
        ...twoQuestionTest('psychometric'),
        duration_seconds: 60,
        timer_mode: 'strict',
        started_at: startedAt.toISOString(),
        expires_at: expiresAt.toISOString(),
        write_expires_at: writeExpiresAt.toISOString(),
        server_now: new Date(now).toISOString(),
        remaining_seconds: 0,
        write_remaining_seconds: 15,
      },
      transport,
      'live',
      { onTimeExpired },
    );
    // Display deadline elapsed — hide blinking 00:00 while write grace remains.
    expect(screen.queryByRole('timer')).not.toBeInTheDocument();
    expect(screen.queryByText(/0:00/)).not.toBeInTheDocument();
    expect(transport.submit).not.toHaveBeenCalled();
    await act(async () => {
      vi.advanceTimersByTime(16_000);
    });
    expect(onTimeExpired).toHaveBeenCalledTimes(1);
    expect(transport.submit).toHaveBeenCalledTimes(1);
  });
});

describe('AssessmentRunner Next debounce', () => {
  it('ignores a second Submit-test click within 300ms', async () => {
    renderRunner(twoQuestionTest('psychometric'), TRANSPORT, 'live', {
      initialAnswers: { q1: 'Alpha', q2: 'Beta' },
    });
    // Both answers hydrated → resume opens on the last question (Submit test).
    expect(screen.getByText(/Question 2 of 2/)).toBeInTheDocument();
    const submitTest = screen.getByRole('button', { name: /Submit test/ });
    // fireEvent bypasses pointer-events so we can assert the debounce itself.
    fireEvent.click(submitTest);
    fireEvent.click(submitTest);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getAllByRole('dialog')).toHaveLength(1);
  });
});

describe('AssessmentRunner timed hard-cut (flexible tag)', () => {
  it('auto-submits at 00:00 even when timer_mode is flexible', async () => {
    const transport = {
      autosave: vi.fn(async () => undefined),
      submit: vi.fn(async () => undefined),
    };
    const onSubmitted = vi.fn();
    const onTimeExpired = vi.fn();
    const started = new Date(Date.now() - 61_000);
    const expires = new Date(started.getTime() + 60_000);
    renderRunner(
      {
        ...twoQuestionTest('psychometric'),
        duration_seconds: 60,
        timer_mode: 'flexible',
        started_at: started.toISOString(),
        expires_at: expires.toISOString(),
        write_expires_at: expires.toISOString(),
        server_now: new Date().toISOString(),
        remaining_seconds: 0,
        write_remaining_seconds: 0,
      },
      transport,
      'live',
      { onSubmitted, onTimeExpired },
    );
    await waitFor(() => expect(onTimeExpired).toHaveBeenCalledTimes(1));
    expect(onSubmitted).not.toHaveBeenCalled();
    expect(transport.submit).toHaveBeenCalledTimes(1);
    expect(screen.getByText(ASSESSMENT_TIMEOUT_MESSAGE)).toBeInTheDocument();
    expect(screen.queryByText(/\+/)).not.toBeInTheDocument();
  });
});

describe('AssessmentRunner debounced autosave', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('batches rapid MCQ clicks into one POST after 300ms with the latest answer', async () => {
    vi.useFakeTimers();
    const transport = {
      autosave: vi.fn(async () => undefined),
      submit: vi.fn(async () => undefined),
    };
    renderRunner(twoQuestionTest(), transport, 'live');
    fireEvent.click(screen.getByRole('radio', { name: /Alpha/ }));
    fireEvent.click(screen.getByRole('radio', { name: /Beta/ }));
    expect(transport.autosave).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(299);
    });
    expect(transport.autosave).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    expect(transport.autosave).toHaveBeenCalledTimes(1);
    expect(transport.autosave).toHaveBeenCalledWith(
      expect.objectContaining({
        question_id: 'q1',
        response: { answer: 'Beta' },
      }),
    );
  });

  it('waits 800ms before autosaving free-text answers', async () => {
    vi.useFakeTimers();
    const transport = {
      autosave: vi.fn(async () => undefined),
      submit: vi.fn(async () => undefined),
    };
    renderRunner(
      test({ type: 'open', options: [], text: 'Essay prompt' }),
      transport,
      'live',
    );
    fireEvent.change(screen.getByRole('textbox', { name: /Open answer/i }), {
      target: { value: 'draft one' },
    });
    await act(async () => {
      vi.advanceTimersByTime(799);
    });
    expect(transport.autosave).not.toHaveBeenCalled();

    fireEvent.change(screen.getByRole('textbox', { name: /Open answer/i }), {
      target: { value: 'draft two' },
    });
    await act(async () => {
      vi.advanceTimersByTime(800);
    });
    expect(transport.autosave).toHaveBeenCalledTimes(1);
    expect(transport.autosave).toHaveBeenCalledWith(
      expect.objectContaining({
        question_id: 'q1',
        response: { answer: 'draft two' },
      }),
    );
  });

  it('keeps successful autosaves silent in the header', async () => {
    vi.useFakeTimers();
    const transport = {
      autosave: vi.fn(async () => undefined),
      submit: vi.fn(async () => undefined),
    };
    renderRunner(twoQuestionTest(), transport, 'live');
    fireEvent.click(screen.getByRole('radio', { name: /Alpha/ }));
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    expect(transport.autosave).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/Saving/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Saved$/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Ready$/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Connection issue/i)).not.toBeInTheDocument();
  });

  it('flushes dirty answers when the tab becomes hidden without waiting for debounce', async () => {
    const transport = {
      autosave: vi.fn(async () => undefined),
      submit: vi.fn(async () => undefined),
    };
    const user = userEvent.setup();
    renderRunner(twoQuestionTest(), transport, 'live');
    await user.click(screen.getByRole('radio', { name: /Alpha/ }));
    expect(transport.autosave).not.toHaveBeenCalled();

    const visibilityDesc = Object.getOwnPropertyDescriptor(Document.prototype, 'visibilityState');
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      get: () => 'hidden',
    });
    try {
      document.dispatchEvent(new Event('visibilitychange'));
      await waitFor(() => expect(transport.autosave).toHaveBeenCalledTimes(1));
      expect(transport.autosave).toHaveBeenCalledWith(
        expect.objectContaining({
          question_id: 'q1',
          response: { answer: 'Alpha' },
        }),
      );
    } finally {
      if (visibilityDesc) Object.defineProperty(Document.prototype, 'visibilityState', visibilityDesc);
      else Reflect.deleteProperty(document, 'visibilityState');
    }
  });

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

describe('AssessmentRunner submit freeze', () => {
  it('keeps a single in-flight submit and shows the submitting overlay', async () => {
    let resolveSubmit: (() => void) | undefined;
    const transport = {
      autosave: vi.fn(async () => undefined),
      submit: vi.fn(
        () =>
          new Promise<void>((resolve) => {
            resolveSubmit = resolve;
          }),
      ),
    };
    const user = userEvent.setup();
    renderRunner(test(), transport, 'live', { initialAnswers: { q1: 3 } });

    await user.click(screen.getByRole('button', { name: /Submit test/i }));
    await user.click(screen.getByRole('button', { name: /Confirm submit/i }));
    expect(transport.submit).toHaveBeenCalledTimes(1);
    // Dialog keeps aria-hidden on the page tree while open; query the overlay explicitly.
    expect(
      screen.getByRole('status', { name: /Submitting your responses/i, hidden: true }),
    ).toBeInTheDocument();
    // Confirm button is disabled + relabeled while the idempotency lock holds.
    expect(screen.getByRole('button', { name: /Submitting your responses/i })).toBeDisabled();

    resolveSubmit?.();
    await waitFor(() =>
      expect(
        screen.queryByRole('status', { name: /Submitting your responses/i, hidden: true }),
      ).not.toBeInTheDocument(),
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
    expect(
      await screen.findByText(/Connection issue — retrying save/i),
    ).toBeInTheDocument();
    expect(transport.autosave).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: /Previous/ }));
    expect(screen.getByText('First question')).toBeInTheDocument();
    await waitFor(() => expect(transport.autosave).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(screen.queryByText(/Connection issue — retrying save/i)).not.toBeInTheDocument(),
    );
  });
});
