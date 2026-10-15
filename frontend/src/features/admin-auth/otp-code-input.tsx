import { useRef, type ClipboardEvent } from 'react';
import { OTP_LENGTH } from './use-admin-otp-login';

interface OtpCodeInputProps {
  value: string;
  onChange: (next: string) => void;
  disabled?: boolean;
  invalid?: boolean;
  describedBy?: string;
}

function focusBox(boxes: Array<HTMLInputElement | null>, index: number) {
  const node = boxes[index];
  node?.focus();
  node?.select();
}

/**
 * Six single-digit boxes. Typing advances, Backspace retreats, and a paste
 * fills from the first box.
 */
export default function OtpCodeInput({
  value,
  onChange,
  disabled = false,
  invalid = false,
  describedBy,
}: OtpCodeInputProps) {
  const boxes = useRef<Array<HTMLInputElement | null>>([]);

  const write = (next: string, focusIndex: number) => {
    const digits = next.replace(/\D/g, '').slice(0, OTP_LENGTH);
    onChange(digits);
    focusBox(boxes.current, Math.min(focusIndex, OTP_LENGTH - 1));
  };

  const onPaste = (event: ClipboardEvent<HTMLDivElement>) => {
    const digits = event.clipboardData.getData('text').replace(/\D/g, '');
    if (!digits) return;
    event.preventDefault();
    write(digits, Math.min(digits.length, OTP_LENGTH) - 1);
  };

  return (
    <div
      role="group"
      aria-label="Verification code"
      aria-describedby={describedBy}
      aria-invalid={invalid || undefined}
      className="flex justify-between gap-1.5"
      onPaste={onPaste}
    >
      {Array.from({ length: OTP_LENGTH }, (_, index) => {
        const digit = value[index] ?? '';
        return (
          <input
            key={index}
            ref={(node) => {
              boxes.current[index] = node;
            }}
            value={digit}
            disabled={disabled}
            inputMode="numeric"
            autoComplete={index === 0 ? 'one-time-code' : 'off'}
            autoFocus={index === 0}
            aria-label={`Digit ${index + 1} of ${OTP_LENGTH}`}
            aria-invalid={invalid || undefined}
            className={`h-12 min-w-0 flex-1 rounded-md border bg-canvas text-center font-mono text-lg tabular-nums text-foreground caret-primary selection:bg-primary/30 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:border-primary disabled:opacity-50 ${
              invalid ? 'border-danger' : 'border-border'
            }`}
            onChange={(event) => {
              const raw = event.target.value.replace(/\D/g, '');
              if (!raw) {
                write(value.slice(0, index) + value.slice(index + 1), index);
                return;
              }
              if (raw.length > 1) {
                write(value.slice(0, index) + raw, index + raw.length - 1);
                return;
              }
              const chars = Array.from({ length: OTP_LENGTH }, (__, slot) => value[slot] ?? '');
              chars[index] = raw;
              const compact = chars.join('').replace(/\D/g, '').slice(0, OTP_LENGTH);
              onChange(compact);
              if (index < OTP_LENGTH - 1) focusBox(boxes.current, index + 1);
            }}
            onKeyDown={(event) => {
              if (event.key === 'Backspace' || (event.key === 'Delete' && digit)) {
                event.preventDefault();
                if (digit) {
                  write(value.slice(0, index) + value.slice(index + 1), index);
                  return;
                }
                if (event.key === 'Backspace' && index > 0) {
                  write(value.slice(0, index - 1) + value.slice(index), index - 1);
                }
                return;
              }
              if (event.key === 'ArrowLeft' && index > 0) {
                event.preventDefault();
                focusBox(boxes.current, index - 1);
              }
              if (event.key === 'ArrowRight' && index < OTP_LENGTH - 1) {
                event.preventDefault();
                focusBox(boxes.current, index + 1);
              }
            }}
            onFocus={(event) => event.currentTarget.select()}
          />
        );
      })}
    </div>
  );
}
