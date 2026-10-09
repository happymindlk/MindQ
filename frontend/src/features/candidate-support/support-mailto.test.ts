import { describe, expect, it } from 'vitest';
import { SUPPORT_EMAIL, buildSupportMailto } from './support-mailto';

function decode(url: string) {
  const parsed = new URL(url);
  return {
    to: parsed.pathname,
    subject: parsed.searchParams.get('subject') ?? '',
    body: parsed.searchParams.get('body') ?? '',
  };
}

describe('buildSupportMailto', () => {
  it('addresses support and pre-fills known candidate details', () => {
    const { to, subject, body } = decode(
      buildSupportMailto({
        fullName: 'Ada Lovelace',
        packageCode: 'HM-ABCDEF-1',
        userAgent: 'Mozilla/5.0 (iPhone)',
        pagePath: '/portal/test/abc',
      }),
    );
    expect(to).toBe(SUPPORT_EMAIL);
    expect(subject).toContain('HM-ABCDEF-1');
    expect(body).toContain('Full Name: Ada Lovelace');
    expect(body).toContain('Package Code: HM-ABCDEF-1');
    expect(body).toContain('Device/Browser: Mozilla/5.0 (iPhone)');
    expect(body).toContain('Applied Role: (please fill in)');
    expect(body).toMatch(/attach screenshots/i);
  });

  it('uses placeholders before sign-in when nothing is known', () => {
    const { body } = decode(
      buildSupportMailto({ fullName: null, packageCode: '  ', userAgent: '', pagePath: '/portal' }),
    );
    expect(body).toContain('Full Name: (please fill in)');
    expect(body).toContain('Package Code: (please fill in)');
    expect(body).toContain('Device/Browser: (please fill in)');
  });

  it('encodes characters that would otherwise break the mailto URL', () => {
    const url = buildSupportMailto({
      fullName: 'Zoë & Co #1?',
      packageCode: 'HM-1',
      userAgent: 'UA',
      pagePath: '/p',
    });
    expect(url).not.toContain('&Co');
    expect(decode(url).body).toContain('Full Name: Zoë & Co #1?');
  });
});
