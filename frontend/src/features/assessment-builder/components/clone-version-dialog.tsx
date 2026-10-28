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
          <NeonButton
            variant="ghost"
            size="sm"
            onClick={() => onOpenChange(false)}
            disabled={cloning}
            className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            Keep v{module.version}
          </NeonButton>
          <NeonButton variant="primary" size="sm" onClick={onConfirm} loading={cloning}>
            <GitBranchPlus className="h-4 w-4" aria-hidden />
            Clone to v{nextVersion}
          </NeonButton>
        </>
      }
    >
      <div className="space-y-3 text-sm">
        <div className="rounded-xl border border-purple-200 bg-purple-50 p-4 text-xs leading-relaxed text-purple-900 dark:border-purple-800/60 dark:bg-purple-950/30 dark:text-purple-200">
          <div className="flex items-start gap-2.5">
            <Lock className="mt-0.5 h-4 w-4 shrink-0 text-[#7048E2] dark:text-purple-400" aria-hidden />
            <span>
              {reason} Editing questions, weights, or timing in place would invalidate scores already collected.
            </span>
          </div>
        </div>
        <ul className="list-disc space-y-1 pl-5 text-xs text-slate-700 dark:text-slate-300">
          <li>All questions, answer keys, media, and timing copy into an editable v{nextVersion} draft.</li>
          <li>v{module.version} keeps serving every suite and candidate already assigned to it.</li>
          <li>Publish v{nextVersion} when ready. New suites will then pick it up.</li>
        </ul>
      </div>
    </NeonDialog>
  );
}
