/** Standardized error for builder API calls, preserving FastAPI's structured detail. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly detail: unknown;

  constructor(message: string, status: number, code: string | null = null, detail: unknown = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.detail = detail;
  }

  get isModuleLocked(): boolean {
    return this.code === 'MODULE_LOCKED';
  }
}

interface ValidationIssue {
  msg?: unknown;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Convert a failed fetch Response into an ApiError.
 *
 * Handles `{detail: string}`, 422 `{detail: [{msg}]}`, and structured
 * `{detail: {code, message}}` bodies.
 *
 * @param res - Non-ok response.
 * @param fallback - Message used when the body carries nothing readable.
 * @returns ApiError ready to throw.
 */
export async function toApiError(res: Response, fallback: string): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    return new ApiError(fallback, res.status);
  }
  const detail = isRecord(body) ? body.detail : null;
  if (typeof detail === 'string' && detail) return new ApiError(detail, res.status, null, detail);
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as ValidationIssue;
    const msg = typeof first.msg === 'string' ? first.msg.replace(/^Value error, /, '') : fallback;
    return new ApiError(msg, res.status, 'VALIDATION', detail);
  }
  if (isRecord(detail)) {
    const message = typeof detail.message === 'string' ? detail.message : fallback;
    const code = typeof detail.code === 'string' ? detail.code : null;
    return new ApiError(message, res.status, code, detail);
  }
  return new ApiError(fallback, res.status, null, body);
}
