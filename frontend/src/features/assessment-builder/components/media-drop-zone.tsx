import { useCallback, useId, useRef, useState } from 'react';
import type { DragEvent, KeyboardEvent } from 'react';
import { AlertTriangle, ImagePlus, Loader2, RefreshCw, Trash2, X } from 'lucide-react';
import { ALLOWED_MEDIA_TYPES, MAX_MEDIA_BYTES } from '../api/media-upload';
import type { StorageClient } from '../api/media-upload';
import { useMediaUpload } from '../hooks/use-media-upload';

interface MediaDropZoneProps {
  moduleId: string;
  value: string | null;
  onChange: (url: string | null) => void;
  disabled?: boolean;
  storage?: StorageClient;
}

const ACCEPT = Object.keys(ALLOWED_MEDIA_TYPES).join(',');

export function MediaDropZone({ moduleId, value, onChange, disabled = false, storage }: MediaDropZoneProps) {
  const { phase, upload, cancel, reset } = useMediaUpload(moduleId, storage);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const lastFileRef = useRef<File | null>(null);
  const hintId = useId();

  const handleFile = useCallback(
    async (file: File | undefined) => {
      if (!file || disabled) return;
      lastFileRef.current = file;
      const result = await upload(file);
      if (result) onChange(result.publicUrl);
    },
    [disabled, onChange, upload],
  );

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    void handleFile(e.dataTransfer.files[0]);
  };

  const openPicker = () => {
    if (!disabled && phase.status !== 'uploading') inputRef.current?.click();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      openPicker();
    }
  };

  const uploading = phase.status === 'uploading';

  return (
    <div className="space-y-2">
      <span className="block text-[11px] font-semibold uppercase tracking-wider text-slate-400">
        Media asset <span className="font-normal normal-case tracking-normal text-slate-500">(optional)</span>
      </span>

      {value ? (
        <figure className="relative overflow-hidden rounded-xl border border-cyan-500/40 bg-slate-950 shadow-[0_0_12px_rgba(6,182,212,0.2)]">
          <img src={value} alt="Question media preview" className="max-h-64 w-full object-contain" loading="lazy" />
          <figcaption className="flex items-center justify-between gap-2 border-t border-slate-800 px-3 py-2">
            <span className="truncate font-mono text-[11px] text-slate-400" title={value}>
              {value.split('/').pop()}
            </span>
            {!disabled && (
              <span className="flex gap-1">
                <button
                  type="button"
                  onClick={openPicker}
                  className="rounded px-2 py-1 text-[11px] font-semibold text-cyan-300 hover:bg-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
                >
                  Replace
                </button>
                <button
                  type="button"
                  onClick={() => {
                    onChange(null);
                    reset();
                  }}
                  aria-label="Remove media"
                  className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-rose-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </span>
            )}
          </figcaption>
        </figure>
      ) : (
        <div
          role="button"
          tabIndex={disabled ? -1 : 0}
          aria-disabled={disabled || uploading}
          aria-describedby={hintId}
          onClick={openPicker}
          onKeyDown={onKeyDown}
          onDragOver={(e) => {
            e.preventDefault();
            if (!disabled) setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          className={`flex min-h-32 cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-6 text-center transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 ${
            dragOver
              ? 'border-cyan-400 bg-cyan-500/10 shadow-[0_0_16px_rgba(6,182,212,0.3)]'
              : 'border-slate-700 bg-slate-950/60 hover:border-cyan-500/50'
          } ${disabled ? 'cursor-not-allowed opacity-50' : ''}`}
        >
          {uploading ? (
            <>
              <Loader2 className="h-6 w-6 animate-spin text-cyan-300" aria-hidden />
              <p className="text-sm text-slate-200" aria-live="polite">
                Uploading {phase.fileName}…
              </p>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  cancel();
                }}
                className="inline-flex items-center gap-1 text-xs font-semibold text-slate-400 hover:text-rose-300"
              >
                <X className="h-3 w-3" aria-hidden /> Cancel
              </button>
            </>
          ) : (
            <>
              <ImagePlus className="h-6 w-6 text-slate-400" aria-hidden />
              <p className="text-sm text-slate-200">
                Drop a matrix, chart, or diagram here, or <span className="font-semibold text-cyan-300">browse</span>
              </p>
              <p id={hintId} className="text-[11px] text-slate-500">
                PNG, JPEG, or WebP · max {Math.round(MAX_MEDIA_BYTES / (1024 * 1024))} MB · stored in assessment-media
              </p>
            </>
          )}
        </div>
      )}

      {phase.status === 'error' && (
        <div
          role="alert"
          className="flex items-start justify-between gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200"
        >
          <span className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            {phase.error.message}
          </span>
          {lastFileRef.current && (phase.error.code === 'network' || phase.error.code === 'unknown' || phase.error.code === 'aborted') && (
            <button
              type="button"
              onClick={() => void handleFile(lastFileRef.current ?? undefined)}
              className="inline-flex shrink-0 items-center gap-1 font-semibold text-rose-100 hover:text-white"
            >
              <RefreshCw className="h-3 w-3" aria-hidden /> Retry
            </button>
          )}
        </div>
      )}

      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        className="sr-only"
        tabIndex={-1}
        aria-hidden
        onChange={(e) => {
          void handleFile(e.target.files?.[0]);
          e.target.value = '';
        }}
      />
    </div>
  );
}
