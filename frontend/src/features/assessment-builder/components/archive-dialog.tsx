import { useState } from 'react';
import { Archive, ShieldCheck } from 'lucide-react';
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
  const confirmed = !live || confirmText.trim().toUpperCase() === 'ARCHIVE';

  return (
    <NeonDialog
      open={open}
      onOpenChange={onOpenChange}
      tone="danger"
      title={`Archive “${module.title}” v${module.version}?`}
      description="Archived modules disappear from the library and suite composer."
      footer={
        <>
          <NeonButton variant="ghost" onClick={() => onOpenChange(false)} disabled={archiving}>
            Cancel
          </NeonButton>
          <NeonButton variant="danger" onClick={onConfirm} disabled={!confirmed} loading={archiving}>
            <Archive className="h-4 w-4" aria-hidden />
            Archive module
          </NeonButton>
        </>
      }
    >
      <div className="space-y-4 text-sm">
        <div className="rounded-xl border border-rose-500/60 bg-rose-500/10 p-4 shadow-[0_0_20px_rgba(244,63,94,0.25)]">
          <p className="font-semibold text-rose-100">This is a soft archive, not a delete.</p>
          <p className="mt-1 flex items-start gap-2 text-rose-200/90">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            Historical candidate responses, scores, and generated reports remain intact and auditable.
          </p>
        </div>
        {live && (
          <div className="space-y-2">
            <p className="text-slate-300">
              This module is linked to{' '}
              <strong className="text-white">
                {module.linkedPackageCount} live suite{module.linkedPackageCount === 1 ? '' : 's'}
              </strong>
              . In-flight candidates finish on the frozen snapshot; it will not be offered for new suites.
            </p>
            <label htmlFor={`archive-confirm-${module.id}`} className="block text-xs text-slate-400">
              Type <span className="font-mono font-semibold text-rose-300">ARCHIVE</span> to confirm
            </label>
            <input
              id={`archive-confirm-${module.id}`}
              className={inputClass}
              autoComplete="off"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
            />
          </div>
        )}
      </div>
    </NeonDialog>
  );
}
