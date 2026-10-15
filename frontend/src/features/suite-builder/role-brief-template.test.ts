import { describe, expect, it } from 'vitest';
import {
  ROLE_BRIEF_TEMPLATE,
  hasRoleBriefTemplate,
  insertRoleBriefTemplate,
} from './role-brief-template';

describe('role brief template', () => {
  it('contains every required heading and field', () => {
    for (const heading of [
      'Position Details',
      'Role Description',
      'Assessment Requirements',
      'HR Contact',
    ]) {
      expect(ROLE_BRIEF_TEMPLATE).toContain(`## ${heading}`);
    }
    for (const field of [
      'Job Title:',
      'Department:',
      'Level:',
      'Purpose:',
      'Main Functions:',
      'Key Responsibilities:',
      'Requirements:',
      'Stage:',
      'Target Focus Areas:',
      'Name:',
      'Designation:',
      'Email:',
      'Phone:',
    ]) {
      expect(ROLE_BRIEF_TEMPLATE).toContain(field);
    }
  });

  it('fills a blank brief', () => {
    expect(insertRoleBriefTemplate('   ')).toBe(ROLE_BRIEF_TEMPLATE);
  });

  it('appends to an existing legacy job description', () => {
    const result = insertRoleBriefTemplate('Senior analyst, Colombo office.\n');
    expect(result.startsWith('Senior analyst, Colombo office.\n\n## Position Details')).toBe(true);
  });

  it('is idempotent', () => {
    const once = insertRoleBriefTemplate('');
    expect(hasRoleBriefTemplate(once)).toBe(true);
    expect(insertRoleBriefTemplate(once)).toBe(once);
  });
});
