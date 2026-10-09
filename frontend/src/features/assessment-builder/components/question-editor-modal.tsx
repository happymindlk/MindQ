import { useId, useMemo, useState } from 'react';
import { AlertTriangle, EyeOff, ShieldAlert } from 'lucide-react';
import { useQuestionEditor } from '../hooks/use-question-editor';
import { QUESTION_TYPE_LABELS } from '../types/question';
import type { BuilderQuestionType, QuestionPayload } from '../types/question';
import type { ModuleKind } from '../types/module';
import type { StorageClient } from '../api/media-upload';
import { CrtBuilder } from './answer-builders/crt-builder';
import { LikertBuilder } from './answer-builders/likert-builder';
import { McqBuilder } from './answer-builders/mcq-builder';
import { SjtBuilder } from './answer-builders/sjt-builder';
import { MarkdownText } from './markdown-preview';
import { MediaDropZone } from './media-drop-zone';
import { FieldLabel, NeonButton, NeonDialog, inputClass } from './primitives';

const DEFAULT_FACETS = ['VR', 'MR', 'Teamwork', 'Pace', 'H:Sinc'] as const;

const TYPES_BY_KIND: Record<ModuleKind, BuilderQuestionType[]> = {
  psychometric: ['sjt', 'mcq', 'likert', 'crt'],
  technical: ['mcq', 'open_ended', 'crt'],
};

interface QuestionEditorModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  moduleId: string;
  moduleKind: ModuleKind;
  initial: QuestionPayload | null;
  knownFacets: string[];
  saving: boolean;
  serverError: string | null;
  onSave: (payload: QuestionPayload) => void;
  storage?: StorageClient;
}

/**
 * Mount with a `key` per question so the reducer re-initialises from `initial`.
 */
export function QuestionEditorModal({
  open,
  onOpenChange,
  moduleId,
  moduleKind,
  initial,
  knownFacets,
  saving,
  serverError,
  onSave,
  storage,
}: QuestionEditorModalProps) {
  const allowed = TYPES_BY_KIND[moduleKind];
  const fallbackType = allowed[0] ?? 'mcq';
  const { question, errors, isValid, dispatch, toPayload } = useQuestionEditor(initial, fallbackType);
  const [promptTab, setPromptTab] = useState<'write' | 'preview'>('write');
  const [showErrors, setShowErrors] = useState(false);
  const uid = useId();

  const facets = useMemo(
    () => [...new Set([...DEFAULT_FACETS, ...knownFacets.filter(Boolean)])].sort((a, b) => a.localeCompare(b)),
    [knownFacets],
  );

  const ids = {
    type: `${uid}-type`,
    prompt: `${uid}-prompt`,
    facet: `${uid}-facet`,
    facetList: `${uid}-facets`,
    rationale: `${uid}-rationale`,
    rubric: `${uid}-rubric`,
  };

  const submit = () => {
    if (!isValid) {
      setShowErrors(true);
      return;
    }
    onSave(toPayload());
  };

  return (
    <NeonDialog
      open={open}
      onOpenChange={onOpenChange}
      title={initial ? 'Edit question' : 'New question'}
      description="Answer keys, weights, and SME rationale never reach the candidate payload."
      widthClass="max-w-3xl"
      footer={
        <>
          <NeonButton variant="ghost" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </NeonButton>
          <NeonButton onClick={submit} loading={saving}>
            {initial ? 'Save question' : 'Add question'}
          </NeonButton>
        </>
      }
    >
      <form
        className="space-y-6"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <FieldLabel htmlFor={ids.type}>Question type</FieldLabel>
            <select
              id={ids.type}
              className={`${inputClass} h-10`}
              value={question.type}
              onChange={(e) => {
                setShowErrors(false);
                dispatch({ kind: 'set-type', type: e.target.value as BuilderQuestionType });
              }}
            >
              {allowed.map((type) => (
                <option key={type} value={type}>
                  {QUESTION_TYPE_LABELS[type]}
                </option>
              ))}
            </select>
          </div>
          <div>
            <FieldLabel htmlFor={ids.facet} hint="Sub-dimension">
              Facet / trait
            </FieldLabel>
            <input
              id={ids.facet}
              list={ids.facetList}
              className={inputClass}
              placeholder="e.g. VR, MR, Teamwork, H:Sinc"
              maxLength={64}
              value={question.facet}
              onChange={(e) => dispatch({ kind: 'set-facet', value: e.target.value })}
            />
            <datalist id={ids.facetList}>
              {facets.map((facet) => (
                <option key={facet} value={facet} />
              ))}
            </datalist>
          </div>
        </div>

        <div>
          <div className="mb-1 flex items-center justify-between">
            <label htmlFor={ids.prompt} className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Prompt <span className="font-normal normal-case tracking-normal text-slate-500">(Markdown)</span>
            </label>
            <div role="tablist" aria-label="Prompt mode" className="inline-flex rounded-md border border-slate-800 p-0.5">
              {(['write', 'preview'] as const).map((tab) => (
                <button
                  key={tab}
                  type="button"
                  role="tab"
                  aria-selected={promptTab === tab}
                  onClick={() => setPromptTab(tab)}
                  className={`rounded px-2 py-0.5 text-[11px] font-semibold capitalize focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 ${
                    promptTab === tab ? 'bg-slate-800 text-cyan-200' : 'text-slate-500 hover:text-slate-200'
                  }`}
                >
                  {tab}
                </button>
              ))}
            </div>
          </div>
          {promptTab === 'write' ? (
            <textarea
              id={ids.prompt}
              rows={5}
              className={`${inputClass} font-mono leading-relaxed`}
              placeholder="**Scenario:** A teammate misses a deadline that affects your deliverable…"
              value={question.prompt}
              onChange={(e) => dispatch({ kind: 'set-prompt', value: e.target.value })}
            />
          ) : (
            <div className="min-h-32 rounded-lg border border-slate-800 bg-slate-950/80 px-3 py-2 text-sm text-slate-100">
              {question.prompt.trim() ? (
                <MarkdownText source={question.prompt} />
              ) : (
                <p className="text-slate-500">Nothing to preview yet.</p>
              )}
            </div>
          )}
        </div>

        <MediaDropZone
          moduleId={moduleId}
          value={question.media_url}
          onChange={(value) => dispatch({ kind: 'set-media', value })}
          storage={storage}
        />

        <section aria-label="Answer builder" className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <h3 className="mb-3 text-sm font-semibold text-white">{QUESTION_TYPE_LABELS[question.type]}</h3>
          {question.type === 'sjt' && <SjtBuilder question={question} dispatch={dispatch} disabled={saving} />}
          {question.type === 'mcq' && <McqBuilder question={question} dispatch={dispatch} disabled={saving} />}
          {question.type === 'likert' && <LikertBuilder question={question} dispatch={dispatch} disabled={saving} />}
          {question.type === 'crt' && <CrtBuilder question={question} dispatch={dispatch} disabled={saving} />}
          {question.type === 'open_ended' && (
            <div>
              <FieldLabel htmlFor={ids.rubric}>Benchmark rubric</FieldLabel>
              <textarea
                id={ids.rubric}
                rows={4}
                className={inputClass}
                placeholder="What a strong answer covers. Used by the evaluator."
                value={question.rubric}
                onChange={(e) => dispatch({ kind: 'open-rubric', value: e.target.value })}
              />
            </div>
          )}
        </section>

        <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
          <label htmlFor={ids.rationale} className="mb-1 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-amber-300">
            <ShieldAlert className="h-3.5 w-3.5" aria-hidden />
            SME rationale
            <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 px-1.5 py-px text-[10px] font-medium normal-case tracking-normal">
              <EyeOff className="h-3 w-3" aria-hidden /> Server-only
            </span>
          </label>
          <textarea
            id={ids.rationale}
            rows={3}
            className={inputClass}
            placeholder="Why the keyed answer is correct; source, norms, or SME sign-off for audit."
            value={question.sme_rationale}
            onChange={(e) => dispatch({ kind: 'set-rationale', value: e.target.value })}
          />
        </div>

        {(showErrors && errors.length > 0) || serverError ? (
          <div role="alert" className="space-y-1 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
            {serverError && (
              <p className="flex items-center gap-2 font-semibold">
                <AlertTriangle className="h-3.5 w-3.5" aria-hidden /> {serverError}
              </p>
            )}
            {showErrors &&
              errors.map((error) => (
                <p key={error} className="pl-5">
                  {error}
                </p>
              ))}
          </div>
        ) : null}
      </form>
    </NeonDialog>
  );
}
