import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../../lib/supabaseClient', () => ({ supabase: { storage: {} } }));

import { QuestionEditorModal } from './question-editor-modal';
import type { QuestionPayload } from '../types/question';

function setup(initial: QuestionPayload | null = null, moduleKind: 'psychometric' | 'technical' = 'psychometric') {
  const onSave = vi.fn();
  const user = userEvent.setup();
  render(
    <QuestionEditorModal
      open
      onOpenChange={() => undefined}
      moduleId="m1"
      moduleKind={moduleKind}
      initial={initial}
      knownFacets={['Extraversion']}
      saving={false}
      serverError={null}
      onSave={onSave}
    />,
  );
  return { user, onSave };
}

describe('QuestionEditorModal', () => {
  it('switches answer builders and resets type-specific state while keeping the prompt', async () => {
    const { user } = setup();
    await user.type(screen.getByRole('textbox', { name: /prompt/i }), 'Pick the best response');
    await user.selectOptions(screen.getByLabelText('Question type'), 'mcq');
    await user.type(screen.getByLabelText('Option A text'), 'Alpha');

    await user.selectOptions(screen.getByLabelText('Question type'), 'sjt');
    expect(screen.getByLabelText('Option A weight')).toHaveValue('3');
    expect(screen.getByLabelText('Option D weight')).toHaveValue('0');
    expect(screen.getByLabelText('Option A text')).toHaveValue('');
    expect(screen.getByRole('textbox', { name: /prompt/i })).toHaveValue('Pick the best response');

    await user.selectOptions(screen.getByLabelText('Question type'), 'crt');
    expect(screen.queryByLabelText('Option A text')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Accepted answer 1')).toBeInTheDocument();
  });

  it('blocks save with inline errors when the payload is invalid', async () => {
    const { user, onSave } = setup();
    await user.click(screen.getByRole('button', { name: 'Add question' }));
    const alert = screen.getByRole('alert');
    expect(within(alert).getByText('Question prompt is required.')).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
  });

  it('saves a single-key MCQ with the glowing Correct Key badge', async () => {
    const { user, onSave } = setup();
    await user.selectOptions(screen.getByLabelText('Question type'), 'mcq');
    await user.type(screen.getByRole('textbox', { name: /prompt/i }), '2 + 2?');
    for (const [key, text] of [['A', '3'], ['B', '4'], ['C', '5'], ['D', '6']] as const) {
      await user.type(screen.getByLabelText(`Option ${key} text`), text);
    }
    await user.click(screen.getByLabelText('Mark option B as correct'));
    expect(screen.getByRole('button', { name: /correct key/i })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Add question' }));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'mcq', mode: 'single', correct_keys: [1], options: ['3', '4', '5', '6'] }),
    );
  });

  it('offers the likert reverse-scoring toggle and only technical types for technical modules', async () => {
    const { user } = setup(null, 'psychometric');
    await user.selectOptions(screen.getByLabelText('Question type'), 'likert');
    const toggle = screen.getByRole('switch', { name: 'Reverse Scored' });
    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-checked', 'true');
    expect(screen.getAllByText('scores 5')[0]).toBeInTheDocument();
  });

  it('saves customised Likert labels that the admin typed over the IPIP defaults', async () => {
    const { user, onSave } = setup();
    await user.selectOptions(screen.getByLabelText('Question type'), 'likert');
    await user.type(screen.getByRole('textbox', { name: /prompt/i }), 'I plan ahead');
    expect(screen.getByLabelText('Label for point 1')).toHaveValue('Very Inaccurate');
    expect(screen.getByLabelText('Label for point 5')).toHaveValue('Very Accurate');

    const custom = ['Never', 'Rarely', 'Sometimes', 'Often', 'Always'];
    for (const [i, label] of custom.entries()) {
      const input = screen.getByLabelText(`Label for point ${i + 1}`);
      await user.clear(input);
      await user.type(input, label);
    }
    await user.click(screen.getByRole('button', { name: 'Add question' }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ type: 'likert', scale_labels: custom }));
  });

  it('blocks saving a Likert item with a cleared label and can reset to defaults', async () => {
    const { user, onSave } = setup();
    await user.selectOptions(screen.getByLabelText('Question type'), 'likert');
    await user.type(screen.getByRole('textbox', { name: /prompt/i }), 'I plan ahead');
    const reset = screen.getByRole('button', { name: /reset to ipip defaults/i });
    expect(reset).toBeDisabled();

    await user.clear(screen.getByLabelText('Label for point 3'));
    expect(screen.getByLabelText('Label for point 3')).toHaveAttribute('aria-invalid', 'true');
    await user.click(screen.getByRole('button', { name: 'Add question' }));
    expect(within(screen.getByRole('alert')).getByText('Every Likert scale label must be filled in.')).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();

    await user.click(reset);
    expect(screen.getByLabelText('Label for point 3')).toHaveValue('Neither Inaccurate nor Accurate');
  });

  it('limits technical modules to MCQ, open-ended, and CRT', () => {
    setup(null, 'technical');
    const options = within(screen.getByLabelText('Question type')).getAllByRole('option').map((o) => o.textContent);
    expect(options).toEqual(['CogniCheck MCQ', 'Open-Ended', 'CRT']);
  });
});
