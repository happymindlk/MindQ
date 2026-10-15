import type { RunnerTest } from '../api/library-api';

export const PREVIEW_ACCESS_CODE = 'preview';
export const PREVIEW_READY = 'hm-preview:ready';
export const PREVIEW_CONFIG = 'hm-preview:config';
export const PREVIEW_TELEMETRY = 'hm-preview:telemetry';

export interface PreviewReadyMessage {
  type: typeof PREVIEW_READY;
}

export interface PreviewConfigMessage {
  type: typeof PREVIEW_CONFIG;
  packageTitle: string;
  tests: RunnerTest[];
}

export interface PreviewTelemetryMessage {
  type: typeof PREVIEW_TELEMETRY;
  assessmentId: string;
  questionId: string;
  elapsedSeconds: number;
}

export type PreviewMessage = PreviewReadyMessage | PreviewConfigMessage | PreviewTelemetryMessage;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

/**
 * Validate an incoming postMessage. Origin must equal ours: preview frames are
 * same-origin by construction (CSP `frame-ancestors 'self'`), so anything else
 * is hostile and ignored.
 *
 * @param event - Raw MessageEvent.
 * @param expectedSource - Window the message must come from.
 * @returns The typed message, or null when it should be ignored.
 */
export function readPreviewMessage(event: MessageEvent, expectedSource: MessageEventSource | null): PreviewMessage | null {
  if (event.origin !== window.location.origin) return null;
  if (expectedSource && event.source !== expectedSource) return null;
  const data: unknown = event.data;
  if (!isRecord(data) || typeof data.type !== 'string') return null;
  switch (data.type) {
    case PREVIEW_READY:
      return { type: PREVIEW_READY };
    case PREVIEW_CONFIG:
      if (!Array.isArray(data.tests)) return null;
      return {
        type: PREVIEW_CONFIG,
        packageTitle: typeof data.packageTitle === 'string' ? data.packageTitle : 'Preview',
        tests: data.tests as RunnerTest[],
      };
    case PREVIEW_TELEMETRY:
      if (typeof data.questionId !== 'string' || typeof data.elapsedSeconds !== 'number') return null;
      return {
        type: PREVIEW_TELEMETRY,
        assessmentId: typeof data.assessmentId === 'string' ? data.assessmentId : '',
        questionId: data.questionId,
        elapsedSeconds: data.elapsedSeconds,
      };
    default:
      return null;
  }
}
