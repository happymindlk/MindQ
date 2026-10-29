import { describe, expect, it } from 'vitest';
import { resolveAssessmentMediaUrl } from './resolve-assessment-media-url';

const REMOTE = 'https://djshmrkerssvpvcxqkqo.supabase.co';
const LOCAL =
  'http://127.0.0.1:54321/storage/v1/object/public/assessment-media/modules/m1/a.png';

describe('resolveAssessmentMediaUrl', () => {
  it('returns null for blank values', () => {
    expect(resolveAssessmentMediaUrl(null, REMOTE)).toBeNull();
    expect(resolveAssessmentMediaUrl('  ', REMOTE)).toBeNull();
  });

  it('rewrites localhost Supabase storage URLs to the configured origin', () => {
    expect(resolveAssessmentMediaUrl(LOCAL, REMOTE)).toBe(
      `${REMOTE}/storage/v1/object/public/assessment-media/modules/m1/a.png`,
    );
  });

  it('leaves already-remote https URLs unchanged', () => {
    const remote = `${REMOTE}/storage/v1/object/public/assessment-media/modules/m1/a.png`;
    expect(resolveAssessmentMediaUrl(remote, REMOTE)).toBe(remote);
  });

  it('maps catalog ICAR paths onto the candidate origin', () => {
    expect(resolveAssessmentMediaUrl('assets/icar/q09_matrix.jpg', REMOTE)).toBe(
      '/assets/icar/q09_matrix.jpg',
    );
    expect(resolveAssessmentMediaUrl('/assets/icar/q09_matrix.jpg', REMOTE)).toBe(
      '/assets/icar/q09_matrix.jpg',
    );
  });

  it('prefixes relative assessment-media paths', () => {
    expect(resolveAssessmentMediaUrl('modules/m1/a.png', REMOTE)).toBe(
      `${REMOTE}/storage/v1/object/public/assessment-media/modules/m1/a.png`,
    );
    expect(
      resolveAssessmentMediaUrl('/storage/v1/object/public/assessment-media/modules/m1/a.png', REMOTE),
    ).toBe(`${REMOTE}/storage/v1/object/public/assessment-media/modules/m1/a.png`);
  });
});
