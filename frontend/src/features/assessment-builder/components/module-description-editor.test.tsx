import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ModuleDescriptionEditor } from './module-editor-drawer';

function renderEditor(overrides: Partial<Parameters<typeof ModuleDescriptionEditor>[0]> = {}) {
  const onSave = vi.fn();
  const onLockedEdit = vi.fn();
  render(
    <ModuleDescriptionEditor
      moduleId="m1"
      description="Original blurb"
      locked={false}
      saving={false}
      onSave={onSave}
      onLockedEdit={onLockedEdit}
      {...overrides}
    />,
  );
  return { onSave, onLockedEdit };
}

describe('ModuleDescriptionEditor', () => {
  it('saves the trimmed description only when dirty', async () => {
    const { onSave } = renderEditor();
    const user = userEvent.setup();
    const save = screen.getByRole('button', { name: 'Save description' });
    expect(save).toBeDisabled();

    const textarea = screen.getByLabelText(/^Description/);
    await user.clear(textarea);
    await user.type(textarea, '  Measures SQL fluency. ');
    expect(save).toBeEnabled();
    await user.click(save);
    expect(onSave).toHaveBeenCalledWith('Measures SQL fluency.');
  });

  it('cancel reverts an unsaved edit and clears the dirty state', async () => {
    renderEditor();
    const user = userEvent.setup();
    const textarea = screen.getByLabelText(/^Description/);
    await user.type(textarea, ' changed');
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(textarea).toHaveValue('Original blurb');
    expect(screen.getByRole('button', { name: 'Save description' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument();
  });

  it('clearing the text saves an empty description', async () => {
    const { onSave } = renderEditor();
    const user = userEvent.setup();
    await user.clear(screen.getByLabelText(/^Description/));
    await user.click(screen.getByRole('button', { name: 'Save description' }));
    expect(onSave).toHaveBeenCalledWith('');
  });

  it('routes edits through the locked guard for locked modules', async () => {
    const { onSave, onLockedEdit } = renderEditor({ locked: true });
    const user = userEvent.setup();
    expect(screen.getByText('Locked')).toBeInTheDocument();
    await user.click(screen.getByLabelText(/^Description/));
    expect(onLockedEdit).toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Save description' })).toBeDisabled();
    expect(onSave).not.toHaveBeenCalled();
  });

  it('syncs the draft when the module description changes externally', () => {
    const { rerender } = render(
      <ModuleDescriptionEditor
        moduleId="m1"
        description="First"
        locked={false}
        saving={false}
        onSave={() => undefined}
        onLockedEdit={() => undefined}
      />,
    );
    rerender(
      <ModuleDescriptionEditor
        moduleId="m1"
        description="Second"
        locked={false}
        saving={false}
        onSave={() => undefined}
        onLockedEdit={() => undefined}
      />,
    );
    expect(screen.getByLabelText(/^Description/)).toHaveValue('Second');
  });
});
