import { describe, expect, it } from 'vitest';
import { ADMIN_KEEP_PATTERNS, resolveKeepAliveKey } from './keep-alive-routes';

describe('resolveKeepAliveKey', () => {
  it('maps primary admin tabs onto stable keep keys', () => {
    expect(resolveKeepAliveKey('/admin', ADMIN_KEEP_PATTERNS)).toBe('admin-home');
    expect(resolveKeepAliveKey('/admin/dashboard', ADMIN_KEEP_PATTERNS)).toBe('admin-home');
    expect(resolveKeepAliveKey('/admin/library', ADMIN_KEEP_PATTERNS)).toBe('admin-library');
    expect(resolveKeepAliveKey('/admin/packages/create', ADMIN_KEEP_PATTERNS)).toBe('admin-suite-create');
    expect(resolveKeepAliveKey('/admin/history', ADMIN_KEEP_PATTERNS)).toBe('admin-history');
    expect(resolveKeepAliveKey('/admin/history/corp-1', ADMIN_KEEP_PATTERNS)).toBe('admin-history');
  });

  it('does not keep parameterized editors or reports', () => {
    expect(resolveKeepAliveKey('/admin/packages/edit/abc', ADMIN_KEEP_PATTERNS)).toBeNull();
    expect(resolveKeepAliveKey('/admin/candidates/c1', ADMIN_KEEP_PATTERNS)).toBeNull();
    expect(resolveKeepAliveKey('/admin/corporates/c1', ADMIN_KEEP_PATTERNS)).toBeNull();
  });
});
