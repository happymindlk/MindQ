import { describe, expect, it } from 'vitest';
import { buildInvitationTemplate } from './invitation-template';

describe('buildInvitationTemplate', () => {
  it('injects a dynamic deadline timestamp in Sri Lanka time', () => {
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
    expect(text).toContain('Deadline: 31 Oct 2026, 5:29 AM (Sri Lanka Time - GMT+5:30)');
    expect(text).toContain('Access PIN: PIN99');
    expect(text).toContain('Backend Suite Assessment Package');
    expect(text).toContain('Acme Talent Team');
    expect(text).not.toMatch(/Assess\s*Pulse/i);
  });

  it('uses No fixed deadline when close_time is missing', () => {
    const text = buildInvitationTemplate(
      { title: 'Open Suite', target_role: null, access_code: 'ABC' },
      'https://mindq.example/portal?code=ABC',
      '',
    );
    expect(text).toContain('Deadline: No fixed deadline');
    expect(text).toContain('The MindQ Team');
    expect(text).toContain('Open Suite Assessment Package');
  });
});
