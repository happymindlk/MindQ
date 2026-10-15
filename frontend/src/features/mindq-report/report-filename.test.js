import { describe, expect, it } from 'vitest';
import {
  reportFilename,
  reportsZipFilename,
  sanitizeFilenamePart,
  uniqueFilename,
} from './report-filename';

describe('reportFilename', () => {
  it('uses the standard "Mind Q Report - [Candidate Full Name].pdf" format', () => {
    expect(reportFilename('Jane Q. Doe')).toBe('Mind Q Report - Jane Q. Doe.pdf');
  });

  it('keeps non-Latin names intact', () => {
    expect(reportFilename('நிலா பெரேரா')).toBe('Mind Q Report - நிலா பெரேரா.pdf');
  });

  it('strips filesystem-illegal characters and collapses whitespace', () => {
    expect(reportFilename('  A/B\\C:*?"<>|  D  ')).toBe('Mind Q Report - A B C D.pdf');
  });

  it('falls back when the name is blank or only illegal characters', () => {
    expect(reportFilename(null)).toBe('Mind Q Report - Candidate.pdf');
    expect(reportFilename('///')).toBe('Mind Q Report - Candidate.pdf');
  });

  it('drops trailing dots that Windows rejects', () => {
    expect(sanitizeFilenamePart('Jr...')).toBe('Jr');
  });

  it('caps very long names', () => {
    expect(sanitizeFilenamePart('x'.repeat(500)).length).toBeLessThanOrEqual(120);
  });
});

describe('reportsZipFilename', () => {
  it('names the zip after the package', () => {
    expect(reportsZipFilename('Senior Engineer')).toBe('Mind Q Reports - Senior Engineer.zip');
    expect(reportsZipFilename('')).toBe('Mind Q Reports - Assessment Suite.zip');
  });
});

describe('uniqueFilename', () => {
  it('suffixes duplicates case-insensitively', () => {
    const used = new Set();
    expect(uniqueFilename('Mind Q Report - Jane.pdf', used)).toBe('Mind Q Report - Jane.pdf');
    expect(uniqueFilename('Mind Q Report - JANE.pdf', used)).toBe('Mind Q Report - JANE (2).pdf');
    expect(uniqueFilename('Mind Q Report - Jane.pdf', used)).toBe('Mind Q Report - Jane (3).pdf');
  });
});
