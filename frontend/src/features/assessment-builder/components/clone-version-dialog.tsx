import { GitBranchPlus, Lock } from 'lucide-react';
import type { AssessmentModule } from '../types/module';
import { NeonButton, NeonDialog } from './primitives';

interface CloneVersionDialogProps {
  module: Pick<AssessmentModule, 'title' | 'version' | 'status' | 'linkedPackageCount'> | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  cloning: boolean;
}

export function CloneVersionDialog({ module, open, onOpenChange, onConfirm, cloning }: CloneVersionDialogProps) {
  if (!module) return null;
  const nextVersion = module.version + 1;
  const reason =
    module.status === 'published'
      ? `v${module.version} is published and immutable.`
      : `v${module.version} is linked to ${module.linkedPackageCount} live suite${module.linkedPackageCount === 1 ? '' : 's'}.`;

  return (
    <NeonDialog
      open={open}
      onOpenChange={onOpenChange}
      tone="violet"
      title={`Clone as New Version (v${nextVersion})`}
      description={module.title}
      footer={
        <>
          <NeonButton variant="ghost" onClick={() => onOpenChange(false)} disabled={cloning}>
            Keep v{module.version}
          </NeonButton>
          <NeonButton variant="violet" onClick={onConfirm} loading={cloning}>
            <GitBranchPlus className="h-4 w-4" aria-hidden />
            Clone to v{nextVersion}
          </NeonButton>
        </>
      }
    >
      <div className="space-y-3 text-sm text-slate-300">
        <p className="flex items-start gap-2 rounded-lg border border-violet-500/40 bg-violet-500/10 px-3 py-2 text-violet-100">
          <Lock className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          {reason} Editing questions, weights, or timing in place would invalidate scores already collected.
        </p>
        <ul className="list-disc space-y-1 pl-5 text-xs text-slate-400">
          <li>All questions, answer keys, media, and timing copy into an editable v{nextVersion} draft.</li>
          <li>v{module.version} keeps serving every suite and candidate already assigned to it.</li>
          <li>Publish v{nextVersion} when ready. New suites will then pick it up.</li>
        </ul>
      </div>
    </NeonDialog>
  );
}
