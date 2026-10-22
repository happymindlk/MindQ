import { useCallback, useMemo, useState } from 'react';
import { AlertTriangle, Archive, GitBranchPlus, Image as ImageIcon, Lock, Pencil, Plus, Rocket, Trash2 } from 'lucide-react';
import { ApiError } from '../../../lib/api-error';
import type { StorageClient } from '../api/media-upload';
import { useBuilderToast } from '../hooks/use-builder-toast';
import { useModuleDetail } from '../hooks/use-module-detail';
import { CATEGORY_LABELS, formatDuration, statusLabel } from '../types/module';
import type { AssessmentModule, ModuleSettings } from '../types/module';
import { QUESTION_TYPE_LABELS } from '../types/question';
import type { QuestionPayload, TemplateQuestion } from '../types/question';
import { CloneVersionDialog } from './clone-version-dialog';
import { ModuleSettingsPanel } from './module-settings-panel';
import { NeonDrawer } from './neon-drawer';
import { FieldLabel, NeonButton, Pill, inputClass } from './primitives';
import { QuestionEditorModal } from './question-editor-modal';
import { CATEGORY_TONES } from './tones';

interface ModuleEditorDrawerProps {
  moduleId: string | null;
  onClose: () => void;
  onModuleChanged: (module: AssessmentModule) => void;
  onOpenModule: (id: string) => void;
  onRequestArchive: (id: string) => void;
  storage?: StorageClient;
}

interface EditorTarget {
  key: string;
  questionId: string | null;
  payload: QuestionPayload | null;
}

function questionPrompt(question: TemplateQuestion): string {
  return question.builder_payload?.prompt || question.question_text || 'Untitled question';
}

interface ModuleTitleEditorProps {
  moduleId: string;
  title: string;
  locked: boolean;
  saving: boolean;
  onSave: (title: string) => void;
  onLockedEdit: () => void;
}

/**
 * Rename a draft assessment. Locked (published/live) versions route to
 * Clone-as-New-Version instead, mirroring the timing settings guard.
 */
function ModuleTitleEditor({ moduleId, title, locked, saving, onSave, onLockedEdit }: ModuleTitleEditorProps) {
  const [draft, setDraft] = useState(title);
  const [prevTitle, setPrevTitle] = useState(title);
  if (prevTitle !== title) {
    setPrevTitle(title);
    setDraft(title);
  }
  const trimmed = draft.trim();
  const dirty = trimmed.length > 0 && trimmed !== title;
  const inputId = `${moduleId}-title`;

  return (
    <section
      aria-labelledby={`${moduleId}-title-heading`}
      className="space-y-3 rounded-xl border border-slate-800 bg-slate-900/80 p-4 backdrop-blur-md"
    >
      <header className="flex items-center justify-between gap-2">
        <h3 id={`${moduleId}-title-heading`} className="text-sm font-semibold text-white">
          Assessment title
        </h3>
        {locked && (
          <span className="inline-flex items-center gap-1 text-[11px] font-medium text-cyan-300">
            <Lock className="h-3 w-3" aria-hidden /> Locked
          </span>
        )}
      </header>
      <div>
        <FieldLabel htmlFor={inputId} hint={locked ? 'Clone as a new version to rename' : undefined}>
          Title
        </FieldLabel>
        <input
          id={inputId}
          className={inputClass}
          value={draft}
          maxLength={255}
          readOnly={locked}
          onFocus={() => locked && onLockedEdit()}
          onChange={(e) => {
            if (locked) {
              onLockedEdit();
              return;
            }
            setDraft(e.target.value);
          }}
          aria-describedby={`${moduleId}-title-help`}
        />
        <p id={`${moduleId}-title-help`} className="mt-1 text-[11px] text-slate-500">
          {locked
            ? 'Published versions keep their title. Clone as a new version, rename the draft, then publish it.'
            : 'Renaming applies to this draft version only.'}
        </p>
      </div>
      <div className="flex justify-end">
        <NeonButton size="sm" disabled={!dirty || locked} loading={saving} onClick={() => onSave(trimmed)}>
          Save title
        </NeonButton>
      </div>
    </section>
  );
}

interface ModuleDescriptionEditorProps {
  moduleId: string;
  description: string | null;
  locked: boolean;
  saving: boolean;
  onSave: (description: string) => void;
  onLockedEdit: () => void;
}

/**
 * Edit a draft assessment's description. Mirrors {@link ModuleTitleEditor}:
 * same lock guard, dirty tracking, and save flow; locked (published/live)
 * versions route to Clone-as-New-Version instead. An empty description
 * clears the stored value.
 */
export function ModuleDescriptionEditor({
  moduleId,
  description,
  locked,
  saving,
  onSave,
  onLockedEdit,
}: ModuleDescriptionEditorProps) {
  const current = description ?? '';
  const [draft, setDraft] = useState(current);
  const [prevDescription, setPrevDescription] = useState(current);
  if (prevDescription !== current) {
    setPrevDescription(current);
    setDraft(current);
  }
  const dirty = draft.trim() !== current.trim();
  const inputId = `${moduleId}-description`;

  return (
    <section
      aria-labelledby={`${moduleId}-description-heading`}
      className="space-y-3 rounded-xl border border-slate-800 bg-slate-900/80 p-4 backdrop-blur-md"
    >
      <header className="flex items-center justify-between gap-2">
        <h3 id={`${moduleId}-description-heading`} className="text-sm font-semibold text-white">
          Assessment description
        </h3>
        {locked && (
          <span className="inline-flex items-center gap-1 text-[11px] font-medium text-cyan-300">
            <Lock className="h-3 w-3" aria-hidden /> Locked
          </span>
        )}
      </header>
      <div>
        <FieldLabel htmlFor={inputId} hint={locked ? 'Clone as a new version to edit' : undefined}>
          Description
        </FieldLabel>
        <textarea
          id={inputId}
          className={`${inputClass} min-h-24 resize-y leading-relaxed`}
          value={draft}
          rows={4}
          placeholder="What this assessment measures, who it is for, and how to interpret it…"
          readOnly={locked}
          onFocus={() => locked && onLockedEdit()}
          onChange={(e) => {
            if (locked) {
              onLockedEdit();
              return;
            }
            setDraft(e.target.value);
          }}
          aria-describedby={`${moduleId}-description-help`}
        />
        <p id={`${moduleId}-description-help`} className="mt-1 text-[11px] text-slate-500">
          {locked
            ? 'Published versions keep their description. Clone as a new version, edit the draft, then publish it.'
            : 'Leave blank to clear the description. Editing applies to this draft version only.'}
        </p>
      </div>
      <div className="flex justify-end gap-2">
        {dirty && !locked && (
          <NeonButton size="sm" variant="ghost" disabled={saving} onClick={() => setDraft(current)}>
            Cancel
          </NeonButton>
        )}
        <NeonButton
          size="sm"
          disabled={!dirty || locked}
          loading={saving}
          onClick={() => onSave(draft.trim())}
        >
          Save description
        </NeonButton>
      </div>
    </section>
  );
}

export function ModuleEditorDrawer({
  moduleId,
  onClose,
  onModuleChanged,
  onOpenModule,
  onRequestArchive,
  storage,
}: ModuleEditorDrawerProps) {
  const { toast } = useBuilderToast();
  const detail = useModuleDetail(moduleId);
  const { module, pending } = detail;
  const [editor, setEditor] = useState<EditorTarget | null>(null);
  const [editorError, setEditorError] = useState<string | null>(null);
  const [cloneOpen, setCloneOpen] = useState(false);

  const locked = module?.isLocked ?? false;
  const questions = useMemo(
    () => (module?.questions ?? []).filter((q) => q.is_active).sort((a, b) => a.position - b.position),
    [module],
  );
  const knownFacets = useMemo(
    () => questions.map((q) => q.builder_payload?.facet ?? '').filter(Boolean),
    [questions],
  );

  const handleError = useCallback(
    (err: unknown, fallback: string) => {
      if (err instanceof ApiError && err.isModuleLocked) {
        setCloneOpen(true);
        return;
      }
      toast({ title: err instanceof Error ? err.message : fallback, variant: 'error' });
    },
    [toast],
  );

  const requireUnlocked = useCallback((): boolean => {
    if (locked) setCloneOpen(true);
    return !locked;
  }, [locked]);

  const onSaveTitle = async (title: string) => {
    try {
      const updated = await detail.saveTitle(title);
      onModuleChanged(updated);
      toast({ title: 'Assessment title saved', variant: 'success' });
    } catch (err) {
      handleError(err, 'Could not save the assessment title.');
    }
  };

  const onSaveDescription = async (description: string) => {
    try {
      const updated = await detail.saveDescription(description);
      onModuleChanged(updated);
      toast({ title: 'Assessment description saved', variant: 'success' });
    } catch (err) {
      handleError(err, 'Could not save the assessment description.');
    }
  };

  const onSaveSettings = async (settings: ModuleSettings) => {
    try {
      const updated = await detail.saveSettings(settings);
      onModuleChanged(updated);
      toast({ title: 'Timing settings saved', variant: 'success' });
    } catch (err) {
      handleError(err, 'Could not save module settings.');
    }
  };

  const onPublish = async () => {
    try {
      const updated = await detail.publish();
      onModuleChanged(updated);
      toast({ title: `v${updated.version} published and locked`, variant: 'success' });
    } catch (err) {
      handleError(err, 'Could not publish this module.');
    }
  };

  const onClone = async () => {
    try {
      const clone = await detail.cloneVersion();
      onModuleChanged(clone);
      setCloneOpen(false);
      toast({ title: `Draft v${clone.version} ready to edit`, variant: 'success' });
      onOpenModule(clone.id);
    } catch (err) {
      setCloneOpen(false);
      handleError(err, 'Could not create a new version.');
    }
  };

  const openEditor = (question: TemplateQuestion | null) => {
    if (!requireUnlocked()) return;
    setEditorError(null);
    setEditor({
      key: question?.id ?? `new-${Date.now()}`,
      questionId: question?.id ?? null,
      payload: question?.builder_payload ?? null,
    });
  };

  const onSaveQuestion = async (payload: QuestionPayload) => {
    if (!editor) return;
    setEditorError(null);
    try {
      await detail.saveQuestion(payload, editor.questionId);
      toast({ title: editor.questionId ? 'Question updated' : 'Question added', variant: 'success' });
      setEditor(null);
    } catch (err) {
      if (err instanceof ApiError && err.isModuleLocked) {
        setEditor(null);
        setCloneOpen(true);
        return;
      }
      setEditorError(err instanceof Error ? err.message : 'Could not save this question.');
    }
  };

  const onRemoveQuestion = async (questionId: string) => {
    if (!requireUnlocked()) return;
    try {
      await detail.removeQuestion(questionId);
      toast({ title: 'Question removed', variant: 'success' });
    } catch (err) {
      handleError(err, 'Could not remove this question.');
    }
  };

  const settings: ModuleSettings | null = module
    ? {
        durationSeconds: module.durationSeconds,
        timerMode: module.timerMode,
        shuffleQuestions: module.shuffleQuestions,
        showTopDisclaimer: module.showTopDisclaimer,
        topDisclaimerText: module.topDisclaimerText,
        showConfidentialityNotice: module.showConfidentialityNotice,
        confidentialityNoticeText: module.confidentialityNoticeText,
      }
    : null;

  return (
    <>
      <NeonDrawer
        open={moduleId !== null}
        onOpenChange={(open) => !open && onClose()}
        title={module?.title ?? 'Loading module…'}
        description={module?.description ?? undefined}
        headerExtra={
          module && (
            <div className="flex flex-wrap items-center gap-1.5 pt-1">
              {module.assessmentCategory ? (
                <Pill tone={CATEGORY_TONES[module.assessmentCategory]}>{CATEGORY_LABELS[module.assessmentCategory]}</Pill>
              ) : (
                <Pill>{module.moduleKind === 'technical' ? 'Technical' : 'Psychometric'}</Pill>
              )}
              <Pill tone={locked ? 'cyan' : 'amber'} icon={locked ? <Lock className="h-3 w-3" aria-hidden /> : undefined}>
                {statusLabel(module)}
              </Pill>
              <Pill>{formatDuration(module.durationSeconds)}</Pill>
              <Pill>{questions.length} Items</Pill>
            </div>
          )
        }
        footer={
          module && (
            <>
              <NeonButton variant="ghost" size="sm" onClick={() => onRequestArchive(module.id)}>
                <Archive className="h-3.5 w-3.5" aria-hidden /> Archive
              </NeonButton>
              {locked ? (
                <NeonButton variant="violet" size="sm" onClick={() => setCloneOpen(true)} loading={pending === 'clone'}>
                  <GitBranchPlus className="h-3.5 w-3.5" aria-hidden /> Clone as New Version (v{module.version + 1})
                </NeonButton>
              ) : (
                <NeonButton
                  size="sm"
                  onClick={onPublish}
                  loading={pending === 'publish'}
                  disabled={questions.length === 0}
                  title={questions.length === 0 ? 'Add at least one question before publishing' : undefined}
                >
                  <Rocket className="h-3.5 w-3.5" aria-hidden /> Publish v{module.version}
                </NeonButton>
              )}
            </>
          )
        }
      >
        {detail.loading && !module && (
          <div className="space-y-3" aria-busy="true">
            <div className="h-40 animate-pulse rounded-xl bg-slate-900" />
            <div className="h-16 animate-pulse rounded-xl bg-slate-900" />
            <div className="h-16 animate-pulse rounded-xl bg-slate-900" />
          </div>
        )}

        {detail.error && (
          <div role="alert" className="flex items-center justify-between gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            <span className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4" aria-hidden /> {detail.error}
            </span>
            <NeonButton size="sm" variant="outline" onClick={() => void detail.reload()}>
              Retry
            </NeonButton>
          </div>
        )}

        {module && settings && (
          <div className="space-y-6">
            {locked && (
              <div className="flex items-start gap-3 rounded-xl border border-cyan-500/40 bg-cyan-500/5 p-4 shadow-[0_0_12px_rgba(6,182,212,0.15)]">
                <Lock className="mt-0.5 h-4 w-4 shrink-0 text-cyan-300" aria-hidden />
                <div className="space-y-1 text-sm">
                  <p className="font-semibold text-cyan-100">Live Test Safety Gate</p>
                  <p className="text-slate-300">
                    {module.status === 'published' ? 'This version is published.' : 'This version is linked to a live suite.'}{' '}
                    Questions, keys, and timing are read-only to protect collected scores.
                  </p>
                </div>
              </div>
            )}

            <ModuleTitleEditor
              moduleId={module.id}
              title={module.title}
              locked={locked}
              saving={pending === 'settings'}
              onSave={(title) => void onSaveTitle(title)}
              onLockedEdit={() => setCloneOpen(true)}
            />

            <ModuleDescriptionEditor
              moduleId={module.id}
              description={module.description}
              locked={locked}
              saving={pending === 'settings'}
              onSave={(description) => void onSaveDescription(description)}
              onLockedEdit={() => setCloneOpen(true)}
            />

            <ModuleSettingsPanel
              moduleId={module.id}
              settings={settings}
              moduleKind={module.moduleKind}
              locked={locked}
              saving={pending === 'settings'}
              onSave={onSaveSettings}
              onLockedEdit={() => setCloneOpen(true)}
            />

            <section aria-labelledby="module-questions-title" className="space-y-3">
              <header className="flex items-center justify-between">
                <h3 id="module-questions-title" className="text-sm font-semibold text-white">
                  Questions <span className="font-mono text-xs text-slate-500">{questions.length}</span>
                </h3>
                <NeonButton size="sm" variant="outline" onClick={() => openEditor(null)} disabled={pending === 'question'}>
                  <Plus className="h-3.5 w-3.5" aria-hidden /> Add question
                </NeonButton>
              </header>

              {questions.length === 0 ? (
                <div className="rounded-xl border border-dashed border-slate-800 px-4 py-8 text-center text-sm text-slate-400">
                  No questions yet. Add SJT, CogniCheck MCQ, Likert, or CRT items to make this module publishable.
                </div>
              ) : (
                <ol className="space-y-2">
                  {questions.map((question, index) => {
                    const payload = question.builder_payload;
                    const legacy = payload === null;
                    return (
                      <li
                        key={question.id}
                        className="group grid grid-cols-[2rem_1fr_auto] items-start gap-3 rounded-xl border border-slate-800 bg-slate-900/70 p-3 transition-colors hover:border-slate-700"
                      >
                        <span className="pt-0.5 font-mono text-xs tabular-nums text-slate-500">{String(index + 1).padStart(2, '0')}</span>
                        <div className="min-w-0 space-y-1.5">
                          <p className="line-clamp-2 text-sm text-slate-100">{questionPrompt(question)}</p>
                          <div className="flex flex-wrap gap-1.5">
                            <Pill tone="violet">
                              {payload ? QUESTION_TYPE_LABELS[payload.type] : question.question_type}
                            </Pill>
                            {payload?.facet && <Pill tone="cyan">{payload.facet}</Pill>}
                            {payload?.type === 'likert' && payload.reverse_scored && <Pill tone="amber">Reverse</Pill>}
                            {payload?.type === 'mcq' && payload.mode === 'multiple' && <Pill>Multi-key</Pill>}
                            {payload?.media_url && (
                              <Pill icon={<ImageIcon className="h-3 w-3" aria-hidden />}>Media</Pill>
                            )}
                            {legacy && <Pill tone="amber">Legacy format</Pill>}
                          </div>
                        </div>
                        <div className="flex gap-1 opacity-80 group-hover:opacity-100">
                          <button
                            type="button"
                            onClick={() => openEditor(question)}
                            disabled={legacy && !locked}
                            title={legacy ? 'Legacy rows cannot be edited in the builder. Recreate the question instead.' : 'Edit question'}
                            aria-label={`Edit question ${index + 1}`}
                            className="rounded p-1.5 text-slate-400 hover:bg-slate-800 hover:text-cyan-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 disabled:opacity-30"
                          >
                            {locked ? <Lock className="h-3.5 w-3.5" /> : <Pencil className="h-3.5 w-3.5" />}
                          </button>
                          <button
                            type="button"
                            onClick={() => void onRemoveQuestion(question.id)}
                            disabled={pending === 'question'}
                            aria-label={`Remove question ${index + 1}`}
                            className="rounded p-1.5 text-slate-400 hover:bg-slate-800 hover:text-rose-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400 disabled:opacity-30"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </li>
                    );
                  })}
                </ol>
              )}
            </section>
          </div>
        )}
      </NeonDrawer>

      {module && editor && (
        <QuestionEditorModal
          key={editor.key}
          open
          onOpenChange={(open) => !open && setEditor(null)}
          moduleId={module.id}
          moduleKind={module.moduleKind}
          initial={editor.payload}
          knownFacets={knownFacets}
          saving={pending === 'question'}
          serverError={editorError}
          onSave={(payload) => void onSaveQuestion(payload)}
          storage={storage}
        />
      )}

      <CloneVersionDialog
        module={module}
        open={cloneOpen}
        onOpenChange={setCloneOpen}
        onConfirm={() => void onClone()}
        cloning={pending === 'clone'}
      />
    </>
  );
}
