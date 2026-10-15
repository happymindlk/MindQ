import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ArchiveDialog } from './archive-dialog';
import { CloneVersionDialog } from './clone-version-dialog';

describe('CloneVersionDialog', () => {
  it('offers the next version and explains why the current one is locked', async () => {
    const onConfirm = vi.fn();
    render(
      <CloneVersionDialog
        module={{ title: 'CogniCheck', version: 1, status: 'published', linkedPackageCount: 0 }}
        open
        onOpenChange={() => undefined}
        onConfirm={onConfirm}
        cloning={false}
      />,
    );
    expect(screen.getByText('Clone as New Version (v2)')).toBeInTheDocument();
    expect(screen.getByText(/v1 is published and immutable/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /clone to v2/i }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('renders nothing without a module', () => {
    const { container } = render(
      <CloneVersionDialog module={null} open onOpenChange={() => undefined} onConfirm={() => undefined} cloning={false} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe('ArchiveDialog', () => {
  it('confirms immediately for unlinked modules and promises history stays intact', async () => {
    const onConfirm = vi.fn();
    render(
      <ArchiveDialog
        module={{ id: 'm1', title: 'Old SJT', version: 2, linkedPackageCount: 0 }}
        open
        onOpenChange={() => undefined}
        onConfirm={onConfirm}
        archiving={false}
      />,
    );
    expect(screen.getByText(/Historical candidate responses, scores, and generated reports remain intact/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /archive module/i }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('requires typing ARCHIVE when the module is linked to live packages', async () => {
    const onConfirm = vi.fn();
    const user = userEvent.setup();
    render(
      <ArchiveDialog
        module={{ id: 'm1', title: 'Live SJT', version: 1, linkedPackageCount: 3 }}
        open
        onOpenChange={() => undefined}
        onConfirm={onConfirm}
        archiving={false}
      />,
    );
    const button = screen.getByRole('button', { name: /archive module/i });
    expect(button).toBeDisabled();
    await user.type(screen.getByLabelText(/to confirm/i), 'archive');
    expect(button).toBeEnabled();
    await user.click(button);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});
