import { useState } from 'react';
import { Trash2, ShieldCheck } from 'lucide-react';
import type { AssessmentModule } from '../types/module';
import { NeonButton, NeonDialog, inputClass } from './primitives';

interface ArchiveDialogProps {
  module: Pick<AssessmentModule, 'id' | 'title' | 'version' | 'linkedPackageCount'> | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  archiving: boolean;
}

/** Mount with `key={module.id}` so the confirmation input resets per module. */
export function ArchiveDialog({ module, open, onOpenChange, onConfirm, archiving }: ArchiveDialogProps) {
  const [confirmText, setConfirmText] = useState('');
  if (!module) return null;
  const live = module.linkedPackageCount > 0;
  const confirmed = confirmText.trim().toUpperCase() === 'DELETE';

  return (
    <NeonDialog
      open={open}
      onOpenChange={onOpenChange}
      tone="danger"
      title={`Delete "${module.title}" v${module.version}?`}
      description="Removes this assessment from the Standard Library and suite composer."
      footer={
        <>
          <NeonButton variant="ghost" onClick={() => onOpenChange(false)} disabled={archiving}>
            Cancel
          </NeonButton>
          <NeonButton variant="danger" onClick={onConfirm} disabled={!confirmed} loading={archiving}>
            <Trash2 className="h-4 w-4" aria-hidden />
            Delete assessment
          </NeonButton>
        </>
      }
    >
      <div className="space-y-4 text-sm">
        <div className="rounded-xl border border-danger/40 bg-danger/10 p-4">
          <p className="font-semibold text-foreground">Soft delete - historical data is preserved.</p>
          <p className="mt-1 flex items-start gap-2 text-muted">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden />
            Candidate responses, scores, and generated reports remain intact and auditable.
          </p>
        </div>
        {live && (
          <p className="text-muted">
            This module is linked to{' '}
            <strong className="text-foreground">
              {module.linkedPackageCount} live suite{module.linkedPackageCount === 1 ? '' : 's'}
            </strong>
            . In-flight candidates finish on the frozen snapshot; it will not be offered for new suites.
          </p>
        )}
        <div className="space-y-2">
          <label htmlFor={`delete-confirm-${module.id}`} className="block text-xs text-muted">
            Type <span className="font-mono font-semibold text-danger">DELETE</span> to confirm
          </label>
          <input
            id={`delete-confirm-${module.id}`}
            className={inputClass}
            autoComplete="off"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
          />
        </div>
      </div>
    </NeonDialog>
  );
}
