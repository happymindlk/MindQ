import { describe, expect, it } from 'vitest';
import { buildInvitationTemplate } from './invitation-template';

describe('buildInvitationTemplate', () => {
  it('injects a dynamic deadline timestamp', () => {
    const text = buildInvitationTemplate(
      {
        title: 'Backend Suite',
        target_role: 'Engineer',
        access_code: 'PIN99',
        close_time: '2026-10-30T23:59:00Z',
      },
      'https://mindq.example/portal?code=PIN99',
      'Acme',
    );
    expect(text).toContain('Deadline: October 30, 2026 at 11:59 PM UTC');
    expect(text).toContain('Access PIN: PIN99');
  });

  it('uses No fixed deadline when close_time is missing', () => {
    const text = buildInvitationTemplate(
      { title: 'Open Suite', target_role: null, access_code: 'ABC' },
      'https://mindq.example/portal?code=ABC',
      '',
    );
    expect(text).toContain('Deadline: No fixed deadline');
  });
});
