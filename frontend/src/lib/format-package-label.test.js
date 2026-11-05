import { describe, expect, it } from 'vitest';
import { formatPackageLabel } from './format-package-label';

describe('formatPackageLabel', () => {
  it.each([
    ['', 'Assessment Package'],
    ['   ', 'Assessment Package'],
    ['Backend Pack', 'Backend Pack Assessment Package'],
    ['Community Coordinator Package', 'Community Coordinator Assessment Package'],
    [
      'Community Coordinator Package assessment package',
      'Community Coordinator Assessment Package',
    ],
    ['Leadership assessment package', 'Leadership Assessment Package'],
    ['Leadership Assessment Package', 'Leadership Assessment Package'],
  ])('formats %j → %j', (raw, expected) => {
    expect(formatPackageLabel(raw)).toBe(expected);
  });
});
