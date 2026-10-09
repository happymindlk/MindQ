import { describe, expect, it, vi } from 'vitest';
import { filterCorporates } from './use-corporates';

vi.mock('../../../lib/adminApi', () => ({ adminApi: {} }));

const ROWS = [
  { id: '1', name: 'Acme Corp', slug: 'acme-corp', contact_email: 'hr@acme.test', logo_url: null },
  { id: '2', name: 'Globex', slug: 'globex', contact_email: null, logo_url: null },
  { id: '3', name: 'Initech', slug: 'initech', contact_email: 'people@initrode.io', logo_url: null },
];

describe('filterCorporates', () => {
  it.each(['', '   ', null, undefined])('returns the input untouched for blank keyword %j', (kw) => {
    expect(filterCorporates(ROWS, kw)).toBe(ROWS);
  });

  it('matches names case-insensitively and ignores surrounding whitespace', () => {
    expect(filterCorporates(ROWS, '  ACME ').map((r) => r.id)).toEqual(['1']);
  });

  it('matches on slug', () => {
    expect(filterCorporates(ROWS, 'globex').map((r) => r.id)).toEqual(['2']);
  });

  it('matches on HR contact email only', () => {
    expect(filterCorporates(ROWS, 'initrode').map((r) => r.id)).toEqual(['3']);
  });

  it('tolerates rows with a null contact email', () => {
    expect(filterCorporates(ROWS, '.test').map((r) => r.id)).toEqual(['1']);
  });

  it('returns an empty list when nothing matches', () => {
    expect(filterCorporates(ROWS, 'zzz-no-match')).toEqual([]);
  });
});
