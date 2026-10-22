import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlarmClock, ArrowRight, ShieldCheck, Target, TimerOff } from 'lucide-react';
import Button from '../../components/ui/Button';
import PageHeader from '../../components/ui/PageHeader';

const GUIDELINES = [
  {
    id: 'purpose',
    icon: Target,
    title: 'Purpose of the Assessment',
    paragraphs: [
      "This assessment is designed to provide insights into different aspects of your abilities, personality, and behaviour. It forms part of the organization's recruitment and selection process.",
    ],
  },
  {
    id: 'deadline',
    icon: AlarmClock,
    title: 'Assessment Deadline',
    paragraphs: [
      'Please ensure that you complete the assessment before the specified deadline. Assessments must be completed within the given submission period.',
      'Each assessment may have a specific time limit. Please make sure you complete the assessment within the allocated time. Once you start the assessment, the timer will begin. Please make sure you are ready to complete the assessment before selecting Start.',
    ],
  },
];

const CONFIDENTIALITY_PARAGRAPHS = [
  {
    lead: 'Proprietary & Confidential Material:',
    body: 'All test content, psychometric scenarios, questions, and formatting are the exclusive intellectual property of MindQ. Copying, reproducing, taking screenshots, screen recording, or sharing any portion of this assessment on public forums, job-prep platforms, social media, or candidate networks is strictly prohibited.',
  },
  {
    lead: 'Prohibition of AI & Automated Assistance:',
    body: 'This assessment measures your individual traits, cognitive abilities, workplace behaviors and sometimes your technical skills & knowledge. The use of generative AI tools, browser extensions, answer bots, or outside assistance to generate or automate responses is strictly forbidden.',
  },
  {
    lead: 'Active AI & Behavioral Integrity Monitoring:',
    body: 'Submissions are analyzed using specialized software designed to detect AI-generated responses, automated inputs, suspicious completion patterns, and unauthorized content exposure.',
  },
  {
    lead: 'Notice of Consequences:',
    body: 'Any violation of these terms, including the use of AI assistance, automated response tools, or unauthorized sharing of assessment materials, will result in the immediate invalidation of your assessment results and notification to the hiring organization, which may lead to candidate disqualification, revocation of job offers, and exclusion from future employment opportunities. Additionally, MindQ reserves the right to restrict access to our assessment platform across all client organizations.',
  },
];

function agreementStorageKey() {
  try {
    const candidateId = window.localStorage.getItem('candidateId');
    return candidateId ? `mindq:confidentiality-agreed:${candidateId}` : 'mindq:confidentiality-agreed';
  } catch {
    return 'mindq:confidentiality-agreed';
  }
}

function readAgreement() {
  try {
    return window.sessionStorage.getItem(agreementStorageKey()) === '1';
  } catch {
    return false;
  }
}

function persistAgreement(agreed) {
  try {
    if (agreed) {
      window.sessionStorage.setItem(agreementStorageKey(), '1');
    } else {
      window.sessionStorage.removeItem(agreementStorageKey());
    }
  } catch {
    // Storage unavailable (private mode / quota); in-memory state still gates this mount.
  }
}

export default function Guidelines() {
  const navigate = useNavigate();
  const [agreed, setAgreed] = useState(readAgreement);

  const onAgreementChange = (event) => {
    const next = event.target.checked;
    setAgreed(next);
    persistAgreement(next);
  };

  return (
    <div className="w-full max-w-xl mx-auto py-6 space-y-4">
      <PageHeader
        title="Assessment Guidelines"
        description="Before you begin, please take a moment to read the following guidelines."
      />

      <div className="rounded-lg border border-border bg-surface divide-y divide-border">
        {GUIDELINES.map(({ id, icon: Icon, title, paragraphs }) => (
          <section key={id} aria-labelledby={`guideline-${id}`} className="flex gap-3 px-4 py-4">
            <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border bg-surface-raised text-primary-text">
              <Icon className="w-4 h-4" aria-hidden="true" />
            </div>
            <div className="min-w-0 space-y-2">
              <h2 id={`guideline-${id}`} className="text-sm font-semibold text-foreground">
                {title}
              </h2>
              {paragraphs.map((text) => (
                <p key={text} className="text-sm text-muted leading-relaxed">
                  {text}
                </p>
              ))}
            </div>
          </section>
        ))}

        <section aria-labelledby="guideline-confidentiality" className="flex gap-3 px-4 py-4">
          <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border bg-surface-raised text-primary-text">
            <ShieldCheck className="w-4 h-4" aria-hidden="true" />
          </div>
          <div className="min-w-0 space-y-2">
            <h2 id="guideline-confidentiality" className="text-sm font-semibold text-foreground">
              CANDIDATE NOTICE &amp; ASSESSMENT CONFIDENTIALITY AGREEMENT
            </h2>
            <p className="text-sm text-muted leading-relaxed">
              By proceeding, you agree to the following terms and conditions:
            </p>
            {CONFIDENTIALITY_PARAGRAPHS.map(({ lead, body }) => (
              <p key={lead} className="text-sm text-muted leading-relaxed">
                <strong className="font-semibold text-foreground">{lead}</strong> {body}
              </p>
            ))}
            <div className="pt-2">
              <label
                htmlFor="confidentiality-agreement"
                className="flex cursor-pointer items-start gap-2.5 text-sm leading-relaxed text-foreground"
              >
                <input
                  id="confidentiality-agreement"
                  type="checkbox"
                  checked={agreed}
                  onChange={onAgreementChange}
                  className="mt-0.5 h-4 w-4 shrink-0 cursor-pointer rounded border-border accent-indigo-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-canvas"
                />
                <span>I have read, understood, and agree to all terms mentioned above.</span>
              </label>
            </div>
          </div>
        </section>
      </div>

      <div
        role="note"
        className="flex gap-3 rounded-lg border border-danger/40 bg-danger/10 px-4 py-3"
      >
        <TimerOff className="mt-0.5 h-5 w-5 shrink-0 text-danger" aria-hidden="true" />
        <p className="text-sm leading-relaxed text-slate-900 dark:text-slate-100">
          If you close your browser or leave this page, the timer will NOT pause. Your answers are saved
          automatically, but the timer keeps running while you are away.
        </p>
      </div>

      <Button onClick={() => navigate('/portal/dashboard')} disabled={!agreed}>
        I understand, continue
        <ArrowRight className="w-4 h-4" aria-hidden="true" />
      </Button>
    </div>
  );
}
