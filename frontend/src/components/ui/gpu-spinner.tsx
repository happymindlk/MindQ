/**
 * CSS border spinner that stays on the compositor thread.
 * Prefer this over SVG `animate-spin` during network waits so main-thread
 * freezes (JSON parse, cache busts) do not halt the rotation.
 */
export function GpuSpinner({ className = '', label }: { className?: string; label?: string }) {
  return (
    <div
      role={label ? 'status' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      className={`h-5 w-5 shrink-0 rounded-full border-2 border-primary border-t-transparent [will-change:transform] transform-gpu animate-spin ${className}`}
    />
  );
}
