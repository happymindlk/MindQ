import React from 'react';

/**
 * Hover/focus tooltip. Keep copy short — ambient context, not instruction.
 */
export default function Tooltip({ content, children, className = '' }) {
  if (!content) return children;

  return (
    <span className={`relative inline-flex items-center group ${className}`}>
      {children}
      <span
        role="tooltip"
        className="
          pointer-events-none absolute z-50 left-1/2 -translate-x-1/2 bottom-[calc(100%+6px)]
          w-max max-w-[16rem] px-2 py-1 rounded-md
          bg-neutral-900 text-neutral-100 text-[11px] leading-snug font-normal normal-case tracking-normal
          opacity-0 translate-y-0.5
          group-hover:opacity-100 group-focus-within:opacity-100
          transition-opacity duration-150 ease-out
          shadow-sm
        "
      >
        {content}
      </span>
    </span>
  );
}
