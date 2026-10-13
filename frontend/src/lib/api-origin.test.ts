import { describe, expect, it } from 'vitest';
import { resolveApiOrigin } from './api-origin';

describe('resolveApiOrigin', () => {
  it('defaults to same-origin when unset or blank', () => {
    expect(resolveApiOrigin(undefined, true)).toBe('');
    expect(resolveApiOrigin('   ', false)).toBe('');
  });

  it('drops insecure HTTP origins in production so the Pages proxy is used', () => {
    expect(resolveApiOrigin('http://52.63.246.238:8000', true)).toBe('');
    expect(resolveApiOrigin('http://localhost:8000', true)).toBe('');
  });

  it('keeps explicit HTTPS origins in production and strips trailing slashes', () => {
    expect(resolveApiOrigin('https://api.example.com/', true)).toBe('https://api.example.com');
    expect(resolveApiOrigin(' https://api-qa.mindqtalent.com ', true)).toBe(
      'https://api-qa.mindqtalent.com',
    );
  });

  it('honours HTTP origins during development', () => {
    expect(resolveApiOrigin('http://127.0.0.1:8000', false)).toBe('http://127.0.0.1:8000');
  });
});
