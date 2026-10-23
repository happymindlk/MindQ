import { afterEach, describe, expect, it } from 'vitest';
import {
  clearSuiteDraft,
  migrateSuiteDraft,
  readSuiteDraft,
  suiteDraftHasContent,
  suiteDraftKey,
  writeSuiteDraft,
} from './suite-draft-cache';

afterEach(() => {
  sessionStorage.clear();
});

describe('suite-draft-cache', () => {
  it('uses distinct keys for create vs edit', () => {
    expect(suiteDraftKey(null)).toBe('mindq:suite-builder:draft:new');
    expect(suiteDraftKey('pkg-1')).toBe('mindq:suite-builder:draft:pkg-1');
  });

  it('round-trips a draft payload', () => {
    writeSuiteDraft(null, {
      corporateId: 'c1',
      title: 'Suite',
      description: 'Brief',
      targetRole: 'Eng',
      openTime: '',
      closeTime: '',
      cartIds: ['m1'],
      moduleOverrides: { m1: [{ id: 'q1' }] },
      customQuestions: [],
    });
    const draft = readSuiteDraft(null);
    expect(draft).toMatchObject({
      v: 1,
      corporateId: 'c1',
      title: 'Suite',
      description: 'Brief',
      cartIds: ['m1'],
    });
    expect(typeof draft.updatedAt).toBe('number');
  });

  it('migrates create draft onto an edit key', () => {
    writeSuiteDraft(null, {
      corporateId: 'c1',
      title: 'Suite',
      description: '',
      targetRole: '',
      openTime: '',
      closeTime: '',
      cartIds: [],
      moduleOverrides: {},
      customQuestions: [],
    });
    migrateSuiteDraft('pkg-9');
    expect(readSuiteDraft(null)).toBeNull();
    expect(readSuiteDraft('pkg-9')?.title).toBe('Suite');
  });

  it('clears a draft key', () => {
    writeSuiteDraft('pkg-1', {
      corporateId: '',
      title: 'X',
      description: '',
      targetRole: '',
      openTime: '',
      closeTime: '',
      cartIds: [],
      moduleOverrides: {},
      customQuestions: [],
    });
    clearSuiteDraft('pkg-1');
    expect(readSuiteDraft('pkg-1')).toBeNull();
  });

  it('detects meaningful content', () => {
    expect(suiteDraftHasContent(null)).toBe(false);
    expect(
      suiteDraftHasContent({
        v: 1,
        updatedAt: 1,
        corporateId: '',
        title: '',
        description: '',
        targetRole: '',
        openTime: '',
        closeTime: '',
        cartIds: [],
        moduleOverrides: {},
        customQuestions: [],
      }),
    ).toBe(false);
    expect(
      suiteDraftHasContent({
        v: 1,
        updatedAt: 1,
        corporateId: '',
        title: '',
        description: 'Role brief',
        targetRole: '',
        openTime: '',
        closeTime: '',
        cartIds: [],
        moduleOverrides: {},
        customQuestions: [],
      }),
    ).toBe(true);
  });
});
