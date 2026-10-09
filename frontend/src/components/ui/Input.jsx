import React, { forwardRef, useId } from 'react';

const Input = forwardRef(({ label, error, icon: Icon, className = '', id, ...props }, ref) => {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const errorId = error ? `${inputId}-error` : undefined;
  return (
    <div className="w-full">
      {label && (
        <label htmlFor={inputId} className="metric-label mb-1.5 block">
          {label}
        </label>
      )}
      <div className="relative">
        {Icon && (
          <div className="absolute inset-y-0 left-0 pl-2.5 flex items-center pointer-events-none">
            <Icon className="h-4 w-4 text-muted" />
          </div>
        )}
        <input
          ref={ref}
          id={inputId}
          aria-invalid={error ? true : undefined}
          aria-describedby={errorId}
          className={`
            block w-full h-9 rounded-md bg-canvas border text-foreground text-sm
            placeholder:text-muted/70
            focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:border-primary
            transition-colors duration-150 ease-out
            ${Icon ? 'pl-9' : 'pl-3'} pr-3
            ${error ? 'border-danger' : 'border-slate-200 dark:border-neutral-800 hover:border-neutral-400 dark:hover:border-neutral-700'}
            ${className}
          `}
          {...props}
        />
      </div>
      {error && <p id={errorId} className="mt-1.5 text-xs text-danger">{error}</p>}
    </div>
  );
});

Input.displayName = 'Input';

export default Input;
