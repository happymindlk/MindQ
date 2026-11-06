import { describe, expect, it } from 'vitest';
import { formatPackageLabel } from './format-package-label';

describe('formatPackageLabel', () => {
  it.each([
    ['', 'Assessment'],
    ['   ', 'Assessment'],
    ['Backend Pack', 'Backend Pack Assessment'],
    ['Community Coordinator Package', 'Community Coordinator Assessment'],
    [
      'Community Coordinator Package assessment package',
      'Community Coordinator Assessment',
    ],
    ['Leadership assessment package', 'Leadership Assessment'],
    ['Leadership Assessment Package', 'Leadership Assessment'],
    ['Operations Assessment', 'Operations Assessment'],
    ['Operations Assessment Assessment', 'Operations Assessment'],
  ])('formats %j → %j', (raw, expected) => {
    expect(formatPackageLabel(raw)).toBe(expected);
  });
});
