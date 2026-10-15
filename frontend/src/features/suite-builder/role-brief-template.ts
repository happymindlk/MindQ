/** Structured skeleton for the Role Assessment Brief (stored in `packages.description`). */
export const ROLE_BRIEF_TEMPLATE = `## Position Details
- Job Title:
- Department:
- Level:

## Role Description
- Purpose:
- Main Functions:
- Key Responsibilities:
- Requirements:

## Assessment Requirements
- Stage:
- Target Focus Areas:

## HR Contact
- Name:
- Designation:
- Email:
- Phone:
`;

const TEMPLATE_MARKER = '## Position Details';

/** True when the brief already contains the template headings. */
export function hasRoleBriefTemplate(brief: string): boolean {
  return brief.includes(TEMPLATE_MARKER);
}

/**
 * Insert the template without discarding existing free-text briefs.
 *
 * @returns The template alone when the brief is blank, otherwise the existing
 * text followed by the template. Unchanged if the template is already present.
 */
export function insertRoleBriefTemplate(brief: string): string {
  if (hasRoleBriefTemplate(brief)) return brief;
  const trimmed = brief.trimEnd();
  return trimmed ? `${trimmed}\n\n${ROLE_BRIEF_TEMPLATE}` : ROLE_BRIEF_TEMPLATE;
}
