import { afterEach, describe, expect, it } from 'vitest';
import { decodeTokenClaims, getCandidateId } from './candidate-identity';

function token(claims) {
  const b64 = (obj) =>
    btoa(JSON.stringify(obj)).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_');
  return `${b64({ alg: 'HS256', typ: 'JWT' })}.${b64(claims)}.sig`;
}

describe('candidate identity', () => {
  afterEach(() => localStorage.clear());

  it('reads sub from the candidate token', () => {
    localStorage.setItem('candidateToken', token({ sub: 'cand-123', typ: 'candidate' }));
    expect(getCandidateId()).toBe('cand-123');
  });

  it('prefers the token over a stale candidateId key', () => {
    localStorage.setItem('candidateToken', token({ sub: 'cand-new' }));
    localStorage.setItem('candidateId', 'cand-old');
    expect(getCandidateId()).toBe('cand-new');
  });

  it('falls back to the legacy key when there is no usable token', () => {
    localStorage.setItem('candidateToken', 'not-a-jwt');
    localStorage.setItem('candidateId', 'cand-legacy');
    expect(getCandidateId()).toBe('cand-legacy');
  });

  it('returns null when nothing is stored', () => {
    expect(getCandidateId()).toBeNull();
    expect(decodeTokenClaims(undefined)).toBeNull();
  });
});
