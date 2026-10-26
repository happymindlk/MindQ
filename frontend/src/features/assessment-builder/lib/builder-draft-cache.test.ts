import { afterEach, describe, expect, it } from 'vitest';
import {
  builderDraftHasContent,
  clearBuilderDraft,
  readBuilderDraft,
  writeBuilderDraft,
} from './builder-draft-cache';

afterEach(() => {
  localStorage.clear();
});

describe('builder-draft-cache', () => {
  it('round-trips a create-module draft', () => {
    writeBuilderDraft({
      kind: 'psychometric',
      category: 'behavioral',
      title: 'New Big Five',
      description: 'Draft desc',
      minutes: 20,
      timerMode: 'flexible',
      shuffle: false,
      showTopDisclaimer: false,
      topDisclaimerText: 'Top',
      showConfidentialityNotice: true,
      confidentialityNoticeText: 'Notice',
    });
    expect(readBuilderDraft()).toMatchObject({
      v: 1,
      kind: 'psychometric',
      title: 'New Big Five',
      minutes: 20,
    });
  });

  it('clears the draft', () => {
    writeBuilderDraft({
      kind: 'technical',
      category: null,
      title: 'X',
      description: '',
      minutes: 15,
      timerMode: 'strict',
      shuffle: false,
      showTopDisclaimer: false,
      topDisclaimerText: '',
      showConfidentialityNotice: false,
      confidentialityNoticeText: '',
    });
    clearBuilderDraft();
    expect(readBuilderDraft()).toBeNull();
  });

  it('detects meaningful content', () => {
    expect(builderDraftHasContent(null)).toBe(false);
    expect(
      builderDraftHasContent({
        v: 1,
        updatedAt: 1,
        kind: 'technical',
        category: null,
        title: '',
        description: '',
        minutes: 0,
        timerMode: 'flexible',
        shuffle: false,
        showTopDisclaimer: false,
        topDisclaimerText: '',
        showConfidentialityNotice: true,
        confidentialityNoticeText: '',
      }),
    ).toBe(false);
    expect(
      builderDraftHasContent({
        v: 1,
        updatedAt: 1,
        kind: 'technical',
        category: null,
        title: 'Skills check',
        description: '',
        minutes: 0,
        timerMode: 'flexible',
        shuffle: false,
        showTopDisclaimer: false,
        topDisclaimerText: '',
        showConfidentialityNotice: true,
        confidentialityNoticeText: '',
      }),
    ).toBe(true);
  });
});
