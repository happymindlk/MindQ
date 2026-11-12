/**
 * Draft legal copy shown in candidate/HR portal modals.
 * Marked draft until counsel finalizes the production text.
 */

export const LEGAL_POLICY_VERSION = '1.0';

export const LEGAL_DRAFT_BANNER =
  'Draft Policy (v1.0) — Subject to final legal review';

export type LegalSection = {
  heading?: string;
  paragraphs: string[];
  bullets?: string[];
};

export type LegalDocument = {
  id: 'privacy' | 'terms';
  title: string;
  sections: LegalSection[];
};

export const privacyPolicy: LegalDocument = {
  id: 'privacy',
  title: 'Privacy Policy',
  sections: [
    {
      paragraphs: [
        LEGAL_DRAFT_BANNER,
        'This Privacy Policy describes how MindQ Talent (“MindQ”, “we”, “us”) collects and processes personal data when you take an assessment through the Candidate Portal on behalf of an inviting organization.',
      ],
    },
    {
      heading: 'Data we collect',
      paragraphs: [
        'In connection with an assessment invitation and session we may process:',
      ],
      bullets: [
        'Identity details you submit (first name, full name, email address)',
        'Access code associated with your invitation or package enrollment',
        'Assessment responses, progress, scores, and generated report content',
        'Session metadata needed to operate the portal (for example timestamps, device/browser signals used for security and support, and technical logs)',
      ],
    },
    {
      heading: 'How we use your data',
      paragraphs: [
        'Candidate data is used to authenticate you, deliver the assessment experience, produce evaluation outputs for the inviting organization, provide technical support, and meet security and compliance obligations.',
        'Data is tenant-isolated by corporate_id so each inviting organization only accesses candidates associated with its own engagement.',
      ],
    },
    {
      heading: 'AI-assisted evaluation',
      paragraphs: [
        'Where enabled for your engagement, MindQ may use AI-assisted evaluation (including Google Gemini on a paid, billing-enabled API tier under non-training provider terms) to help synthesize narratives or grade eligible open-ended items. Prompts and responses for paid Gemini API workloads are not used to train Google models under those terms; abuse-monitoring retention by the provider may still apply.',
      ],
    },
    {
      heading: 'Security',
      paragraphs: [
        'We protect personal data with industry-standard controls appropriate to the service: TLS encryption in transit and AES-256 encryption at rest for hosted database and private report object storage.',
      ],
    },
    {
      heading: 'Retention, access, and erasure',
      paragraphs: [
        'Candidate identity and assessment records are retained for the life of the hiring engagement with the client organization, or until an authorized erasure request is processed.',
        'You (or the inviting organization / authorized ops) may request access or erasure. Erasure is performed through the platform’s deletion pipeline (authorized DELETE of the candidate record), which removes personal assessment data subject to that pipeline.',
        'Aggregated and irreversibly anonymized assessment metrics may be retained for psychometric validation, norming, and research purposes.',
      ],
    },
    {
      heading: 'Contact',
      paragraphs: [
        'For privacy questions related to an assessment, use Technical Support in the Candidate Portal or contact the inviting organization that sponsored your invitation.',
      ],
    },
  ],
};

export const termsAndConditions: LegalDocument = {
  id: 'terms',
  title: 'Terms & Conditions',
  sections: [
    {
      paragraphs: [
        LEGAL_DRAFT_BANNER,
        'These Terms & Conditions govern your use of the MindQ Talent Candidate Portal and related assessment materials.',
      ],
    },
    {
      heading: 'Honest and unassisted completion',
      paragraphs: [
        'You agree to complete the assessment honestly and without unauthorized assistance. You must not share answers, use prohibited aids, or otherwise misrepresent your own responses.',
      ],
    },
    {
      heading: 'Confidentiality of assessment content',
      paragraphs: [
        'Assessment questions, scenarios, scoring logic, and related materials are confidential. You must not copy, record, photograph, distribute, or disclose assessment content to others.',
      ],
    },
    {
      heading: 'Acceptable use for HR clients',
      paragraphs: [
        'Organizations using MindQ do so for legitimate talent assessment and related HR purposes. Clients must process candidate data in accordance with applicable law and their agreements with MindQ, including any Data Processing Agreement.',
      ],
    },
    {
      heading: 'Hiring decisions',
      paragraphs: [
        'MindQ provides assessment tooling and analytical outputs to the inviting organization. Hiring, selection, and employment decisions rest solely with that organization. MindQ does not guarantee or determine any employment outcome.',
      ],
    },
    {
      heading: 'Research metrics',
      paragraphs: [
        'Aggregated and irreversibly anonymized assessment metrics may be retained for psychometric validation, norming, and research purposes.',
      ],
    },
  ],
};

export function getLegalDocument(id: LegalDocument['id']): LegalDocument {
  return id === 'privacy' ? privacyPolicy : termsAndConditions;
}
