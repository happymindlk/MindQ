import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import {
  DEFAULT_CONFIDENTIALITY_NOTICE_TEXT,
  DEFAULT_TOP_DISCLAIMER_TEXT,
} from '../types/module';
import type { ModuleSettings } from '../types/module';
import { ModuleSettingsPanel } from './module-settings-panel';

const SETTINGS: ModuleSettings = {
  durationSeconds: 1200,
  timerMode: 'flexible',
  shuffleQuestions: false,
  showTopDisclaimer: false,
  topDisclaimerText: DEFAULT_TOP_DISCLAIMER_TEXT,
  showConfidentialityNotice: true,
  confidentialityNoticeText: DEFAULT_CONFIDENTIALITY_NOTICE_TEXT,
};

function renderPanel(overrides: Partial<Parameters<typeof ModuleSettingsPanel>[0]> = {}) {
  const onSave = vi.fn();
  const onLockedEdit = vi.fn();
  render(
    <ModuleSettingsPanel
      moduleId="m1"
      settings={SETTINGS}
      moduleKind="psychometric"
      locked={false}
      saving={false}
      onSave={onSave}
      onLockedEdit={onLockedEdit}
      {...overrides}
    />,
  );
  return { onSave, onLockedEdit };
}

describe('ModuleSettingsPanel candidate notices', () => {
  it('renders both notice toggles for psychometric modules with default texts', () => {
    renderPanel();
    expect(screen.getByRole('switch', { name: /Show disclaimer above every question/ })).toHaveAttribute(
      'aria-checked',
      'false',
    );
    expect(screen.getByRole('switch', { name: /Show confidentiality/ })).toHaveAttribute(
      'aria-checked',
      'true',
    );
    expect(screen.getByLabelText(/Confidentiality notice text/)).toHaveValue(
      DEFAULT_CONFIDENTIALITY_NOTICE_TEXT,
    );
    expect(screen.queryByLabelText(/Top disclaimer text/)).not.toBeInTheDocument();
  });

  it('does not render the notices section for technical modules', () => {
    renderPanel({ moduleKind: 'technical' });
    expect(screen.queryByText('Candidate notices')).not.toBeInTheDocument();
  });

  it('saves edited notice fields with the timing settings', async () => {
    const { onSave } = renderPanel();
    const user = userEvent.setup();
    await user.click(screen.getByRole('switch', { name: /Show disclaimer above every question/ }));
    const topText = screen.getByLabelText(/Top disclaimer text/);
    await user.clear(topText);
    await user.type(topText, 'Custom top note.');
    await user.click(screen.getByRole('button', { name: /Save settings/ }));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        durationSeconds: 1200,
        showTopDisclaimer: true,
        topDisclaimerText: 'Custom top note.',
        showConfidentialityNotice: true,
        confidentialityNoticeText: DEFAULT_CONFIDENTIALITY_NOTICE_TEXT,
      }),
    );
  });

  it('routes edits through the locked guard for locked modules', async () => {
    const { onSave, onLockedEdit } = renderPanel({ locked: true });
    const user = userEvent.setup();
    await user.click(screen.getByRole('switch', { name: /Show disclaimer above every question/ }));
    expect(onLockedEdit).toHaveBeenCalled();
    expect(screen.getByRole('button', { name: /Save settings/ })).toBeDisabled();
    expect(onSave).not.toHaveBeenCalled();
  });
});
