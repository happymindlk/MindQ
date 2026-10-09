import { describe, expect, it } from 'vitest';
import {
  reportFilename,
  reportsZipFilename,
  sanitizeFilenamePart,
  uniqueFilename,
} from './report-filename';

describe('reportFilename', () => {
  it('uses the standard "MindQ Report - [Candidate Full Name].pdf" format', () => {
    expect(reportFilename('Jane Q. Doe')).toBe('MindQ Report - Jane Q. Doe.pdf');
  });

  it('keeps non-Latin names intact', () => {
    expect(reportFilename('நிலா பெரேரா')).toBe('MindQ Report - நிலா பெரேரா.pdf');
  });

  it('strips filesystem-illegal characters and collapses whitespace', () => {
    expect(reportFilename('  A/B\\C:*?"<>|  D  ')).toBe('MindQ Report - A B C D.pdf');
  });

  it('falls back when the name is blank or only illegal characters', () => {
    expect(reportFilename(null)).toBe('MindQ Report - Candidate.pdf');
    expect(reportFilename('///')).toBe('MindQ Report - Candidate.pdf');
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
    expect(reportsZipFilename('Senior Engineer')).toBe('MindQ Reports - Senior Engineer.zip');
    expect(reportsZipFilename('')).toBe('MindQ Reports - Assessment Suite.zip');
  });
});

describe('uniqueFilename', () => {
  it('suffixes duplicates case-insensitively', () => {
    const used = new Set();
    expect(uniqueFilename('MindQ Report - Jane.pdf', used)).toBe('MindQ Report - Jane.pdf');
    expect(uniqueFilename('MindQ Report - JANE.pdf', used)).toBe('MindQ Report - JANE (2).pdf');
    expect(uniqueFilename('MindQ Report - Jane.pdf', used)).toBe('MindQ Report - Jane (3).pdf');
  });
});
