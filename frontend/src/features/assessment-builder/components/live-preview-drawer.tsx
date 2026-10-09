import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, Loader2, Monitor, RefreshCw, Smartphone } from 'lucide-react';
import { libraryApi } from '../api/library-api';
import type { RunnerTest } from '../api/library-api';
import { PREVIEW_ACCESS_CODE, PREVIEW_CONFIG, PREVIEW_READY, readPreviewMessage } from '../lib/preview-protocol';
import type { PreviewConfigMessage } from '../lib/preview-protocol';
import { NeonDrawer } from './neon-drawer';
import { NeonButton, Pill } from './primitives';

interface LivePreviewDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  packageTitle: string;
  moduleIds: string[];
  moduleOverrides?: Record<string, unknown[]>;
}

type PreviewState =
  | { status: 'loading' }
  | { status: 'ready'; tests: RunnerTest[] }
  | { status: 'error'; message: string };

const PREVIEW_SRC = `/portal?code=${PREVIEW_ACCESS_CODE}`;

export function LivePreviewDrawer({ open, onOpenChange, packageTitle, moduleIds, moduleOverrides }: LivePreviewDrawerProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [state, setState] = useState<PreviewState>({ status: 'loading' });
  const [device, setDevice] = useState<'desktop' | 'mobile'>('desktop');
  const [frameKey, setFrameKey] = useState(0);
  const [frameReady, setFrameReady] = useState(false);

  const load = useCallback(async () => {
    if (moduleIds.length === 0) {
      setState({ status: 'error', message: 'Add at least one module to preview the candidate flow.' });
      return;
    }
    setState({ status: 'loading' });
    try {
      const tests = await libraryApi.previewPackage(moduleIds, moduleOverrides);
      setState({ status: 'ready', tests });
    } catch (err) {
      setState({ status: 'error', message: err instanceof Error ? err.message : 'Could not build the preview.' });
    }
  }, [moduleIds, moduleOverrides]);

  useEffect(() => {
    if (!open) return;
    setFrameReady(false);
    void load();
  }, [open, load]);

  useEffect(() => {
    if (!open) return undefined;
    const onMessage = (event: MessageEvent) => {
      const message = readPreviewMessage(event, iframeRef.current?.contentWindow ?? null);
      if (message?.type === PREVIEW_READY) setFrameReady(true);
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [open, frameKey]);

  useEffect(() => {
    if (!frameReady || state.status !== 'ready') return;
    const message: PreviewConfigMessage = { type: PREVIEW_CONFIG, packageTitle, tests: state.tests };
    iframeRef.current?.contentWindow?.postMessage(message, window.location.origin);
  }, [frameReady, packageTitle, state]);

  const restart = () => {
    setFrameReady(false);
    setFrameKey((k) => k + 1);
    void load();
  };

  const totalItems = state.status === 'ready' ? state.tests.reduce((sum, t) => sum + t.questions.length, 0) : 0;

  return (
    <NeonDrawer
      open={open}
      onOpenChange={onOpenChange}
      widthClass="max-w-3xl"
      title="Live Preview"
      description="Exactly what candidates see. Answers and telemetry stay in this window and are never saved."
      headerExtra={
        <div className="flex flex-wrap items-center gap-1.5 pt-1">
          <Pill tone="cyan">{moduleIds.length} modules</Pill>
          {state.status === 'ready' && <Pill>{totalItems} items</Pill>}
          <Pill tone="amber">Sandbox</Pill>
        </div>
      }
      footer={
        <>
          <div role="radiogroup" aria-label="Preview device" className="mr-auto inline-flex rounded-lg border border-slate-700 p-0.5">
            {(
              [
                { id: 'desktop', icon: Monitor, label: 'Desktop' },
                { id: 'mobile', icon: Smartphone, label: 'Mobile' },
              ] as const
            ).map(({ id, icon: Icon, label }) => (
              <button
                key={id}
                type="button"
                role="radio"
                aria-checked={device === id}
                aria-label={label}
                onClick={() => setDevice(id)}
                className={`rounded-md p-1.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 ${
                  device === id ? 'bg-cyan-500/20 text-cyan-200' : 'text-slate-400 hover:text-white'
                }`}
              >
                <Icon className="h-4 w-4" />
              </button>
            ))}
          </div>
          <NeonButton variant="outline" size="sm" onClick={restart}>
            <RefreshCw className="h-3.5 w-3.5" aria-hidden /> Restart preview
          </NeonButton>
        </>
      }
    >
      {state.status === 'error' ? (
        <div role="alert" className="flex items-start gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-3 text-sm text-rose-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          {state.message}
        </div>
      ) : (
        <div className="relative flex h-full min-h-[60vh] justify-center">
          {(state.status === 'loading' || !frameReady) && (
            <div className="absolute inset-0 z-10 flex items-center justify-center gap-2 text-sm text-slate-300" aria-live="polite">
              <Loader2 className="h-4 w-4 animate-spin text-cyan-300" aria-hidden /> Building candidate preview…
            </div>
          )}
          <iframe
            key={frameKey}
            ref={iframeRef}
            src={PREVIEW_SRC}
            title="Candidate test preview"
            sandbox="allow-scripts allow-same-origin allow-forms"
            className={`h-full min-h-[60vh] rounded-xl border border-slate-800 bg-white transition-all ${
              device === 'mobile' ? 'w-[390px]' : 'w-full'
            } ${frameReady ? 'opacity-100' : 'opacity-0'}`}
          />
        </div>
      )}
    </NeonDrawer>
  );
}
