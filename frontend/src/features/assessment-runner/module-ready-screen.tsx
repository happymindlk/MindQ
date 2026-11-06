/**
 * Instruction gate shown before a module attempt starts.
 * The countdown / IN_PROGRESS transition must wait for this CTA.
 */

interface ModuleReadyScreenProps {
  title: string;
  description?: string | null;
  durationSeconds?: number | null;
  onBegin: () => void;
  beginLabel?: string;
  busy?: boolean;
  error?: string | null;
  onExit?: () => void;
  exitLabel?: string;
}

/**
 * Render the pre-start instruction screen for a candidate (or preview) module.
 *
 * @param props - Module metadata plus begin / exit handlers.
 * @returns Instruction UI with an explicit ready CTA.
 */
export function ModuleReadyScreen({
  title,
  description,
  durationSeconds,
  onBegin,
  beginLabel = "I'm ready to begin",
  busy = false,
  error = null,
  onExit,
  exitLabel = 'Back to dashboard',
}: ModuleReadyScreenProps) {
  const minutes =
    durationSeconds && durationSeconds > 0 ? Math.max(1, Math.round(durationSeconds / 60)) : null;

  return (
    <div className="mx-auto flex w-full max-w-md flex-col items-center gap-4 py-16 text-center">
      {onExit ? (
        <button
          type="button"
          onClick={onExit}
          className="self-start text-xs text-muted hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          ← {exitLabel}
        </button>
      ) : null}
      <p className="text-lg font-semibold text-foreground">{title}</p>
      {description ? <p className="text-sm leading-relaxed text-muted">{description}</p> : null}
      {minutes ? (
        <p className="text-xs text-muted">
          Timed module · about {minutes} minute{minutes === 1 ? '' : 's'}. The countdown starts when
          you begin.
        </p>
      ) : (
        <p className="text-xs text-muted">The assessment starts when you confirm you are ready.</p>
      )}
      {error ? (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : null}
      <button
        type="button"
        onClick={onBegin}
        disabled={busy}
        aria-busy={busy || undefined}
        className="inline-flex h-10 items-center justify-center rounded-md bg-[#7048E2] px-4 text-sm font-medium text-white hover:bg-[#5e3cc4] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#7048E2] disabled:cursor-not-allowed disabled:opacity-60"
      >
        {busy ? 'Starting…' : beginLabel}
      </button>
    </div>
  );
}
