import React from 'react';
import { useNavigate } from 'react-router-dom';
import { AlarmClock, ArrowRight, ClipboardCheck, Target, TimerOff } from 'lucide-react';
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
  {
    id: 'preparation',
    icon: ClipboardCheck,
    title: 'Before You Begin',
    paragraphs: [
      'Choose a quiet place where you can concentrate without interruptions and ensure you have a stable internet connection before starting.',
      'Answer each question honestly and based on your own abilities, preferences, or typical behaviour. There are no right or wrong answers for questions that assess your personality or behavioural preferences.',
    ],
  },
];

export default function Guidelines() {
  const navigate = useNavigate();

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

      <Button onClick={() => navigate('/portal/dashboard')}>
        I understand, continue
        <ArrowRight className="w-4 h-4" aria-hidden="true" />
      </Button>
    </div>
  );
}
