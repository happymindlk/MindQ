import { describe, expect, it } from 'vitest';
import { normalizeModuleStatus } from './module-status';

describe('normalizeModuleStatus', () => {
  it.each([
    ['COMPLETED', 'completed'],
    ['completed', 'completed'],
    ['IN_PROGRESS', 'in_progress'],
    ['in-progress', 'in_progress'],
    ['NOT_STARTED', 'not_started'],
    ['', 'not_started'],
    [null, 'not_started'],
    [undefined, 'not_started'],
    ['bogus', 'not_started'],
  ])('maps %s → %s', (raw, expected) => {
    expect(normalizeModuleStatus(raw)).toBe(expected);
  });
});
