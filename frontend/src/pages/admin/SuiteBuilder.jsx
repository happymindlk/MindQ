import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Check, ChevronDown, Eye, FileText, GripVertical, Plus, Save, Search, Trash2, X } from 'lucide-react';
import Button from '../../components/ui/Button';
import Input from '../../components/ui/Input';
import Badge from '../../components/ui/Badge';
import Modal from '../../components/ui/Modal';
import { useToast } from '../../components/ui/useToast';
import { adminApi } from '../../lib/adminApi';
import { friendlyErrorMessage } from '../../lib/friendly-error';
import {
  ComposerDndProvider,
  ComposerLibraryPane,
  ComposerSequence,
} from '../../features/assessment-builder/components/package-composer';
import { LivePreviewDrawer } from '../../features/assessment-builder/components/live-preview-drawer';
import { catalogFromRow } from '../../features/assessment-builder/lib/catalog';
import {
  fromSriLankaInputValue,
  toSriLankaInputValue,
} from '../../features/package-schedule/sri-lanka-time';
import { scheduleWindowError } from '../../features/package-schedule/schedule-window';
import {
  hasRoleBriefTemplate,
  insertRoleBriefTemplate,
} from '../../features/suite-builder/role-brief-template';

function moduleMinutes(mod) {
  const seconds = Number(mod.duration_seconds) || Number(mod.time_limit_minutes) * 60 || 0;
  return seconds > 0 ? Math.round(seconds / 60) : null;
}

const fieldClass =
  'w-full rounded-md bg-white dark:bg-slate-950 border border-slate-200 dark:border-slate-800 text-foreground text-sm px-3 py-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:border-primary placeholder:text-muted/70';

function emptyCustom() {
  return {
    prompt: '',
    question_type: 'mcq',
    options: ['', '', '', ''],
    correct_answer_or_rubric: '',
    evaluated_competency: 'Technical',
    weight: 3,
  };
}

function CompanySelect({ corporates, value, disabled, onChange }) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef(null);
  const selected = corporates.find((c) => c.id === value);

  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (event) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        id="company"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-describedby="company-help"
        onClick={() => setOpen((prev) => !prev)}
        className={`${fieldClass} h-9 flex items-center justify-between gap-2 text-left disabled:opacity-50`}
      >
        <span className={selected ? 'truncate' : 'text-muted/70 truncate'}>
          {selected ? selected.name : 'Select company'}
        </span>
        <ChevronDown className="w-3.5 h-3.5 text-slate-400 dark:text-slate-500 shrink-0" aria-hidden />
      </button>
      {open && !disabled && (
        <ul
          role="listbox"
          className="absolute z-20 mt-1 w-full max-h-64 overflow-y-auto rounded-md border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 py-1 shadow-lg"
        >
          {corporates.length === 0 ? (
            <li className="px-3 py-2 text-sm text-slate-400 dark:text-slate-500">No clients yet</li>
          ) : (
            corporates.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={c.id === value}
                  className={`w-full text-left px-3 py-2 text-sm text-slate-900 dark:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800 ${
                    c.id === value ? 'bg-indigo-50 text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-300' : ''
                  }`}
                  onClick={() => {
                    onChange(c.id);
                    setOpen(false);
                  }}
                >
                  {c.name}
                </button>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}

function ModuleChip({ mod, questions, editable, onRemove, onQuestionsChange, dragHandle }) {
  const [open, setOpen] = useState(false);
  const items = Array.isArray(questions) ? questions : [];
  const canExpand = items.length > 0;

  return (
    <div className="rounded-md border border-slate-200 dark:border-slate-800 bg-surface-raised overflow-hidden">
      <div className="flex items-start gap-2 px-2.5 py-2">
        {dragHandle ?? (
          <GripVertical className="w-3.5 h-3.5 text-slate-400 dark:text-slate-500 mt-0.5 shrink-0" aria-hidden />
        )}
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-foreground truncate">{mod.title}</p>
          <p className="text-[11px] uppercase tracking-wider text-slate-500 dark:text-slate-400 mt-0.5 tabular-data">
            {mod.module_kind} · {items.length || mod.question_count || 0} items
            {moduleMinutes(mod) != null && ` · ${moduleMinutes(mod)} min`}
            {mod.version > 1 && ` · v${mod.version}`}
          </p>
          {mod.upgraded_from_version != null && (
            <p className="mt-1 text-[11px] text-indigo-600 dark:text-indigo-300">
              Updated from v{mod.upgraded_from_version} to the latest published version
            </p>
          )}
        </div>
        {canExpand && (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="p-1 rounded text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100"
            aria-expanded={open}
            aria-label={open ? 'Collapse questions' : 'Expand questions'}
          >
            <ChevronDown
              className={`w-3.5 h-3.5 transition-transform ${open ? 'rotate-0' : '-rotate-90'}`}
            />
          </button>
        )}
        {onRemove && (
          <button
            type="button"
            onClick={() => onRemove(mod.id)}
            className="p-1 rounded text-slate-500 dark:text-slate-400 hover:text-danger"
            aria-label={`Remove ${mod.title}`}
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
      {open && (
        <ul className="border-t border-slate-200 dark:border-slate-800 divide-y divide-slate-200 dark:divide-slate-800 bg-surface">
          {items.map((q, index) => {
            const prompt = q.prompt || q.text || '';
            const qtype = q.type || q.question_type || 'likert';
            return (
              <li key={q.id || index} className="px-2.5 py-2 space-y-1.5">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-mono text-slate-400 dark:text-slate-500">
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  <span className="text-[10px] uppercase tracking-wider text-slate-400 dark:text-slate-500">
                    {qtype}
                  </span>
                </div>
                <textarea
                  rows={2}
                  disabled={!editable}
                  className={`${fieldClass} resize-y min-h-[40px] text-xs`}
                  value={prompt}
                  onChange={(e) => {
                    if (!onQuestionsChange) return;
                    const next = items.map((row, i) => {
                      if (i !== index) return row;
                      const updated = { ...row };
                      if ('prompt' in updated || !('text' in updated)) {
                        updated.prompt = e.target.value;
                      } else {
                        updated.text = e.target.value;
                      }
                      return updated;
                    });
                    onQuestionsChange(mod.id, next);
                  }}
                />
                {Array.isArray(q.options) && q.options.length > 0 && (
                  <div className="grid grid-cols-1 gap-1">
                    {q.options.map((opt, oi) => (
                      <input
                        key={oi}
                        disabled={!editable}
                        className={`${fieldClass} h-7 text-xs`}
                        value={opt ?? ''}
                        onChange={(e) => {
                          if (!onQuestionsChange) return;
                          const next = items.map((row, i) => {
                            if (i !== index) return row;
                            const opts = [...(row.options || [])];
                            opts[oi] = e.target.value;
                            return { ...row, options: opts };
                          });
                          onQuestionsChange(mod.id, next);
                        }}
                      />
                    ))}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export default function SuiteBuilder() {
  const { packageId: routePackageId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { toast } = useToast();
  const loadPackageId = routePackageId || searchParams.get('packageId');
  const [modules, setModules] = useState([]);
  const [corporates, setCorporates] = useState([]);
  const [search, setSearch] = useState('');
  const [corporateId, setCorporateId] = useState('');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [targetRole, setTargetRole] = useState('');
  const [threshold, setThreshold] = useState('');
  const [openTime, setOpenTime] = useState('');
  const [closeTime, setCloseTime] = useState('');
  const [cartIds, setCartIds] = useState([]);
  const [moduleOverrides, setModuleOverrides] = useState({});
  const [customQuestions, setCustomQuestions] = useState([]);
  const [packageId, setPackageId] = useState(loadPackageId || null);
  const [status, setStatus] = useState('draft');
  const [saveState, setSaveState] = useState('idle');
  const [publishError, setPublishError] = useState(null);
  const [isPublishing, setIsPublishing] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);
  const [share, setShare] = useState(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [libraryPickId, setLibraryPickId] = useState('');
  const [syncTargetId, setSyncTargetId] = useState('');
  const [syncModal, setSyncModal] = useState(null);
  const skipSave = useRef(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [modRows, corpRows] = await Promise.all([
          adminApi.listGlobalModules(),
          adminApi.listCorporates(),
        ]);
        if (cancelled) return;
        // Merge rather than replace: the package load may already have added
        // cart modules with package-specific fields, and either request can land first.
        setModules((prev) => {
          const map = new Map(prev.map((m) => [m.id, m]));
          (modRows || []).forEach((row) => map.set(row.id, { ...map.get(row.id), ...row }));
          return Array.from(map.values());
        });
        setCorporates(corpRows || []);
      } catch (err) {
        console.error(err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!loadPackageId) return;
    let cancelled = false;
    (async () => {
      try {
        const pkg = await adminApi.getAdminPackage(loadPackageId);
        if (cancelled) return;
        skipSave.current = true;
        setPackageId(pkg.id);
        setCorporateId(pkg.corporate_id);
        setTitle(pkg.title || '');
        setDescription(pkg.description || '');
        setTargetRole(pkg.target_role || '');
        setThreshold(
          pkg.passing_threshold == null || pkg.passing_threshold === ''
            ? ''
            : String(pkg.passing_threshold),
        );
        setOpenTime(toSriLankaInputValue(pkg.open_time));
        setCloseTime(toSriLankaInputValue(pkg.close_time));
        setStatus(pkg.status);
        setCustomQuestions(pkg.custom_questions || []);
        setCartIds((pkg.modules || []).map((m) => m.module_id).filter(Boolean));
        const overrides = {};
        (pkg.modules || []).forEach((m) => {
          if (m.module_id && Array.isArray(m.questions) && m.questions.length > 0) {
            overrides[m.module_id] = m.questions;
          }
        });
        setModuleOverrides(overrides);
        setModules((prev) => {
          const map = new Map(prev.map((m) => [m.id, m]));
          (pkg.modules || []).forEach((m) => {
            if (!m.module_id) return;
            const existing = map.get(m.module_id) || {};
            map.set(m.module_id, {
              ...existing,
              id: m.module_id,
              slug: m.slug,
              title: m.title,
              description: m.description,
              module_kind: m.module_kind,
              time_limit_minutes: m.time_limit_minutes,
              duration_seconds: m.duration_seconds,
              timer_mode: m.timer_mode,
              version: m.version,
              upgraded_from_version: m.upgraded_from_version ?? null,
              question_count: m.question_count,
              is_active: m.is_active,
              questions: m.questions || existing.questions || [],
            });
          });
          return Array.from(map.values());
        });
        const upgraded = (pkg.modules || []).filter((m) => m.upgraded_from_version != null);
        if (upgraded.length > 0 && pkg.status !== 'published') {
          // Persist the resolved versions so the draft no longer points at stale ones.
          skipSave.current = false;
          toast({
            title: `${upgraded.length} module${upgraded.length === 1 ? '' : 's'} updated to the latest published version`,
            variant: 'success',
          });
        }
        if (pkg.status === 'published') {
          setShare({
            access_code: pkg.access_code,
            review_path: pkg.review_token ? `/client/review/${pkg.review_token}` : null,
          });
        }
      } catch (err) {
        console.error(err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadPackageId]);

  const moduleById = useMemo(() => {
    const map = new Map();
    modules.forEach((m) => map.set(m.id, m));
    return map;
  }, [modules]);

  const cart = useMemo(
    () => cartIds.map((id) => moduleById.get(id)).filter(Boolean),
    [cartIds, moduleById],
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return modules.filter((m) => {
      if (!q) return true;
      return (
        m.title.toLowerCase().includes(q) ||
        (m.description || '').toLowerCase().includes(q) ||
        m.module_kind.toLowerCase().includes(q)
      );
    });
  }, [modules, search]);

  const catalog = useMemo(() => modules.map((m) => catalogFromRow(m)), [modules]);
  const catalogById = useMemo(() => new Map(catalog.map((m) => [m.id, m])), [catalog]);
  const technicalModules = useMemo(
    () => filtered.filter((m) => (m.module_kind || '').toLowerCase() !== 'psychometric'),
    [filtered],
  );

  const selectedIds = useMemo(() => new Set(cartIds), [cartIds]);

  const locked = status === 'published';

  const cartQuestionsFor = useCallback(
    (mod) => {
      if (!mod) return [];
      if (Array.isArray(moduleOverrides[mod.id])) return moduleOverrides[mod.id];
      return Array.isArray(mod.questions) ? mod.questions : [];
    },
    [moduleOverrides],
  );

  const addModule = useCallback(
    async (mod, nextIds) => {
      if (!mod?.id || locked || selectedIds.has(mod.id)) return;
      setCartIds((prev) => (Array.isArray(nextIds) ? nextIds : [...prev, mod.id]));
      // Eager local snapshot for every module kind so suite edits stay isolated.
      setModuleOverrides((prev) => {
        if (prev[mod.id]) return prev;
        const qs = Array.isArray(mod.questions) ? structuredClone(mod.questions) : [];
        return { ...prev, [mod.id]: qs };
      });
      if (packageId) {
        try {
          const result = await adminApi.addTemplateToPackage(packageId, mod.id);
          if (Array.isArray(result.questions)) {
            setModuleOverrides((prev) => ({
              ...prev,
              [mod.id]: structuredClone(result.questions),
            }));
          }
        } catch (err) {
          // Already attached is fine; other errors surface to the user.
          if (!String(err.message || '').toLowerCase().includes('already')) {
            toast({
              title: friendlyErrorMessage(err, 'Could not add this assessment to the suite.'),
              variant: 'error',
            });
          }
        }
      }
    },
    [locked, selectedIds, packageId, toast],
  );

  const onModuleQuestionsChange = useCallback((moduleId, nextQuestions) => {
    setModuleOverrides((prev) => ({ ...prev, [moduleId]: nextQuestions }));
  }, []);

  const syncCustomToMaster = useCallback(
    async (index, templateId) => {
      const q = customQuestions[index];
      if (!q || !String(q.prompt || '').trim() || !templateId) return;
      try {
        await adminApi.syncQuestionToMaster(templateId, {
          prompt: q.prompt,
          question_type: q.question_type,
          options: (q.options || []).filter(Boolean),
          correct_answer_or_rubric: q.correct_answer_or_rubric || '',
          evaluated_competency: q.evaluated_competency || 'Technical',
          weight: Number(q.weight) || 3,
        });
        setCustomQuestions((prev) =>
          prev.map((row, i) => (i === index ? { ...row, syncedToMaster: true } : row)),
        );
        toast({ title: 'Saved to Standard Library', variant: 'success' });
        const refreshed = await adminApi.listGlobalModules();
        setModules(refreshed || []);
      } catch (err) {
        toast({
          title: friendlyErrorMessage(err, 'Could not save this question to the Standard Library.'),
          variant: 'error',
        });
      }
    },
    [customQuestions, toast],
  );

  const scheduleError = useMemo(
    () => scheduleWindowError(openTime, closeTime),
    [openTime, closeTime],
  );

  const persist = useCallback(async () => {
    if (!corporateId || !title.trim() || locked || scheduleError) return null;
    setSaveState('saving');
    const schedulePayload = {
      open_time: fromSriLankaInputValue(openTime),
      close_time: fromSriLankaInputValue(closeTime),
    };
    const customPayload = customQuestions
      .filter((q) => String(q.prompt || '').trim())
      .map((q) => ({
        id: q.id || undefined,
        prompt: q.prompt,
        question_type: q.question_type,
        options: (q.options || []).filter(Boolean),
        correct_answer_or_rubric: q.correct_answer_or_rubric || '',
        evaluated_competency: q.evaluated_competency || 'Technical',
        weight: Number(q.weight) || 3,
      }));
    const thresholdValue =
      threshold === '' || threshold == null ? null : Number(threshold);
    const overridesPayload = {};
    cartIds.forEach((id) => {
      if (Array.isArray(moduleOverrides[id])) {
        overridesPayload[id] = moduleOverrides[id];
      }
    });
    try {
      let saved;
      if (packageId) {
        saved = await adminApi.updateAdminPackage(packageId, {
          title: title.trim(),
          description,
          ...schedulePayload,
          target_role: targetRole.trim() || null,
          passing_threshold: Number.isFinite(thresholdValue) ? thresholdValue : null,
          corporate_id: corporateId,
          module_ids: cartIds,
          custom_questions: customPayload,
          module_question_overrides: overridesPayload,
        });
      } else {
        saved = await adminApi.saveDraftPackage(
          {
            corporate_id: corporateId,
            title: title.trim(),
            description,
            ...schedulePayload,
            target_role: targetRole.trim() || null,
            passing_threshold: Number.isFinite(thresholdValue) ? thresholdValue : null,
            module_ids: cartIds,
            custom_questions: customPayload,
            module_question_overrides: overridesPayload,
          },
          null,
        );
      }
      if (saved.id !== packageId) setPackageId(saved.id);
      setSaveState('saved');
      if (!loadPackageId && saved.id) {
        skipSave.current = true;
        navigate(`/admin/packages/edit/${saved.id}`, { replace: true });
      }
      return saved;
    } catch (err) {
      console.error(err);
      setSaveState('error');
      throw err;
    }
  }, [
    corporateId,
    title,
    description,
    openTime,
    closeTime,
    scheduleError,
    targetRole,
    threshold,
    cartIds,
    customQuestions,
    moduleOverrides,
    moduleById,
    locked,
    packageId,
    loadPackageId,
    navigate,
  ]);

  useEffect(() => {
    if (skipSave.current) {
      skipSave.current = false;
      return;
    }
    const timer = window.setTimeout(() => {
      persist().catch(() => {});
    }, 900);
    setSaveState((prev) => (prev === 'idle' ? 'idle' : 'saving'));
    return () => window.clearTimeout(timer);
  }, [persist]);

  const onComposerAdd = useCallback(
    (moduleId, nextIds) => {
      const mod = moduleById.get(moduleId);
      if (mod) addModule(mod, nextIds);
    },
    [addModule, moduleById],
  );

  const removeFromCart = useCallback((id) => {
    setCartIds((prev) => prev.filter((m) => m !== id));
    setModuleOverrides((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }, []);

  const previewOverrides = useMemo(() => {
    const out = {};
    cartIds.forEach((id) => {
      if (Array.isArray(moduleOverrides[id]) && moduleOverrides[id].length > 0) {
        out[id] = moduleOverrides[id];
      }
    });
    return out;
  }, [cartIds, moduleOverrides]);

  const onPublish = async () => {
    setPublishError(null);
    if (scheduleError) {
      setPublishError(scheduleError);
      return;
    }
    try {
      const saved = await persist();
      const id = saved?.id || packageId;
      if (!id) {
        setPublishError('Save a draft first');
        return;
      }
      if (!cart.length && !customQuestions.some((q) => q.prompt.trim())) {
        setPublishError('Add a module or custom question');
        return;
      }
      setIsPublishing(true);
      const published = await adminApi.publishDraftPackage(id);
      setStatus('published');
      setShare({
        access_code: published.access_code,
        review_path: published.review_path,
        candidate_path: published.candidate_path,
      });
    } catch (err) {
      setPublishError(err.message || 'Publish failed');
    } finally {
      setIsPublishing(false);
    }
  };

  const onUpdateDraft = async () => {
    setPublishError(null);
    if (scheduleError) {
      setPublishError(scheduleError);
      return;
    }
    setIsUpdating(true);
    try {
      await persist();
    } catch (err) {
      setPublishError(err.message || 'Update failed');
    } finally {
      setIsUpdating(false);
    }
  };

  const reviewUrl = share?.review_path
    ? `${window.location.origin}${share.review_path}`
    : '';

  return (
    <div className="h-[calc(100vh-5.5rem)] min-h-[32rem] flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3 shrink-0">
        <h1 className="text-xl font-semibold tracking-tight text-slate-900 dark:text-slate-100">Suite Builder</h1>
        <div className="flex items-center gap-3">
          <Badge variant={locked ? 'locked' : 'draft'} showDot>
            {locked ? 'Published (Locked)' : 'Draft (Editable)'}
          </Badge>
          <div className="inline-flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400 font-mono" aria-live="polite">
            {saveState === 'saving' && (
              <>
                <span className="h-1.5 w-1.5 rounded-full bg-indigo-500 animate-pulse" aria-hidden />
                Saving...
              </>
            )}
            {saveState === 'saved' && !locked && (
              <>
                <Check className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" aria-hidden />
                Draft
              </>
            )}
          </div>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setPreviewOpen(true)}
            disabled={cartIds.length === 0}
            title={cartIds.length === 0 ? 'Add a module to preview' : 'Preview the candidate flow'}
          >
            <Eye className="w-3.5 h-3.5" />
            Live Preview
          </Button>
          {!locked && packageId && (
            <Button
              size="sm"
              onClick={onUpdateDraft}
              disabled={isUpdating}
              isLoading={isUpdating}
            >
              Update Draft
            </Button>
          )}
          <Button
            size="sm"
            variant="secondary"
            onClick={onPublish}
            disabled={locked || isPublishing}
            isLoading={isPublishing}
          >
            Publish
          </Button>
        </div>
      </div>

      {publishError && (
        <p className="text-sm text-danger shrink-0" role="alert">
          {publishError}
        </p>
      )}

      {share && (
        <div className="shrink-0 rounded-lg border border-slate-200 dark:border-slate-800 bg-surface px-3 py-2.5 grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
          <div>
            <p className="uppercase tracking-wider text-slate-500 dark:text-slate-400">Access code</p>
            <p className="mt-0.5 font-mono tabular-nums text-foreground">{share.access_code}</p>
          </div>
          <div className="min-w-0">
            <p className="uppercase tracking-wider text-slate-500 dark:text-slate-400">HR review</p>
            <p className="mt-0.5 font-mono text-foreground truncate">{reviewUrl}</p>
          </div>
        </div>
      )}

      <ComposerDndProvider
        cartIds={cartIds}
        locked={locked}
        catalogById={catalogById}
        onReorder={setCartIds}
        onAdd={onComposerAdd}
      >
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] gap-3 min-h-0">
        <section className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 flex flex-col min-h-0">
          <div className="px-3 py-2.5 border-b border-slate-200 dark:border-slate-800">
            <p className="uppercase tracking-wider text-xs text-slate-500 dark:text-slate-400 mb-2">
              Published Modules
            </p>
            <Input
              icon={Search}
              placeholder="Search assessments"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search assessments"
            />
          </div>
          <div className="flex-1 overflow-y-auto">
            <ComposerLibraryPane
              modules={catalog}
              search={search}
              selectedIds={selectedIds}
              locked={locked}
              onAdd={(id) => {
                const mod = moduleById.get(id);
                if (mod) addModule(mod);
              }}
            />
          </div>
        </section>

        <section className="rounded-lg border border-slate-200 dark:border-slate-800 bg-surface flex flex-col min-h-0">
          <div className="px-3 py-2.5 border-b border-slate-200 dark:border-slate-800 space-y-3 max-h-[55%] overflow-y-auto shrink-0">
            <p className="uppercase tracking-wider text-xs text-slate-500 dark:text-slate-400">Assessment Suite</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <div>
                <label className="uppercase tracking-wider text-xs text-slate-500 dark:text-slate-400 mb-1.5 block" htmlFor="company">
                  Company
                </label>
                <CompanySelect
                  corporates={corporates}
                  value={corporateId}
                  disabled={locked}
                  onChange={setCorporateId}
                />
                <p id="company-help" className="mt-1.5 text-xs text-slate-400 dark:text-slate-500">
                  Select a client. To add a new client, create them on the Dashboard first.
                </p>
              </div>
              <Input
                label="Suite Title"
                value={title}
                disabled={locked}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Junior Data Analyst"
              />
              <Input
                label="Target role"
                value={targetRole}
                disabled={locked}
                onChange={(e) => setTargetRole(e.target.value)}
                placeholder="Analyst"
              />
              <Input
                label="Threshold"
                type="number"
                min={0}
                max={100}
                step="0.01"
                value={threshold}
                disabled={locked}
                onChange={(e) => setThreshold(e.target.value)}
                placeholder="70"
              />
              <Input
                label="Opens (IST / GMT+5:30)"
                type="datetime-local"
                value={openTime}
                disabled={locked}
                onChange={(e) => setOpenTime(e.target.value)}
              />
              <Input
                label="Closes (IST / GMT+5:30)"
                type="datetime-local"
                value={closeTime}
                disabled={locked}
                onChange={(e) => setCloseTime(e.target.value)}
                error={scheduleError || undefined}
              />
            </div>
            <p className="text-xs text-slate-400 dark:text-slate-500">
              {locked
                ? 'To change the deadline of a live suite, use Extend deadline in Assessment History.'
                : 'Leave blank for no limit. Candidates cannot start before the open time or begin new modules after the close time.'}
            </p>

            <div>
              <div className="flex items-center justify-between gap-2 mb-1.5">
                <label
                  htmlFor="role-assessment-brief"
                  className="uppercase tracking-wider text-xs text-slate-500 dark:text-slate-400"
                >
                  Role Assessment Brief
                </label>
                {!locked && (
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => setDescription((prev) => insertRoleBriefTemplate(prev))}
                    disabled={hasRoleBriefTemplate(description)}
                    title={
                      hasRoleBriefTemplate(description)
                        ? 'Template already inserted'
                        : 'Insert the standard brief headings'
                    }
                  >
                    <FileText className="w-3.5 h-3.5" aria-hidden />
                    Insert Brief Template
                  </Button>
                )}
              </div>
              <textarea
                id="role-assessment-brief"
                rows={5}
                maxLength={50000}
                disabled={locked}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Position details, role description, assessment requirements and HR contact. Used for role-fit scoring."
                aria-describedby="role-assessment-brief-help"
                className={`${fieldClass} resize-y min-h-[96px] max-h-[40vh] font-sans leading-relaxed disabled:opacity-60`}
              />
              <p id="role-assessment-brief-help" className="mt-1.5 text-xs text-slate-400 dark:text-slate-500">
                {description.length.toLocaleString()} / 50,000 characters
              </p>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-3">
            <ComposerSequence
              cartIds={cart.map((m) => m.id)}
              locked={locked}
              emptyState={
                <div className="rounded-md border border-dashed border-slate-200 dark:border-slate-800 px-3 py-8 text-center">
                  <p className="text-xs uppercase tracking-wider text-slate-500 dark:text-slate-400">No assessments yet</p>
                  <p className="text-sm text-muted mt-1">
                    Drag published modules here, or use Add. Drag to set the candidate sequence.
                  </p>
                </div>
              }
              renderItem={(id, handle) => {
                const mod = moduleById.get(id);
                if (!mod) return null;
                return (
                  <ModuleChip
                    mod={mod}
                    dragHandle={handle}
                    questions={cartQuestionsFor(mod)}
                    editable={!locked}
                    onQuestionsChange={!locked ? onModuleQuestionsChange : undefined}
                    onRemove={locked ? undefined : removeFromCart}
                  />
                );
              }}
            />

            <div className="pt-1">
              <div className="flex flex-col gap-2 mb-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="uppercase tracking-wider text-xs text-slate-500 dark:text-slate-400">
                    Select from Standard Library
                  </p>
                </div>
                {!locked && (
                  <div className="flex items-center gap-2">
                    <select
                      className={`${fieldClass} h-9 flex-1`}
                      value={libraryPickId}
                      onChange={(e) => setLibraryPickId(e.target.value)}
                      aria-label="Select technical assessment from the Standard Library"
                    >
                      <option value="">Technical assessment…</option>
                      {technicalModules.map((m) => (
                        <option key={m.id} value={m.id} disabled={selectedIds.has(m.id)}>
                          {m.title}
                          {selectedIds.has(m.id) ? ' (in suite)' : ''}
                        </option>
                      ))}
                    </select>
                    <Button
                      type="button"
                      size="sm"
                      disabled={!libraryPickId || selectedIds.has(libraryPickId)}
                      onClick={() => {
                        const mod = moduleById.get(libraryPickId);
                        if (mod) {
                          addModule(mod);
                          setLibraryPickId('');
                        }
                      }}
                    >
                      Add
                    </Button>
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between mb-2">
                <p className="uppercase tracking-wider text-xs text-slate-500 dark:text-slate-400">Custom technical</p>
                {!locked && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setCustomQuestions((prev) => [...prev, emptyCustom()])}
                  >
                    <Plus className="w-3.5 h-3.5" />
                    Add
                  </Button>
                )}
              </div>
              <ul className="space-y-2">
                {customQuestions.map((q, index) => (
                  <li key={q.id || index} className="rounded-md border border-slate-200 dark:border-slate-800 p-2.5 space-y-2">
                    <div className="flex items-start gap-2">
                      <span className="text-[11px] font-mono tabular-nums text-slate-500 dark:text-slate-400 mt-2">
                        {String(index + 1).padStart(2, '0')}
                      </span>
                      <textarea
                        rows={2}
                        disabled={locked}
                        className={`${fieldClass} resize-y min-h-[48px]`}
                        placeholder="Question prompt"
                        value={q.prompt}
                        onChange={(e) => {
                          const next = [...customQuestions];
                          next[index] = { ...q, prompt: e.target.value };
                          setCustomQuestions(next);
                        }}
                      />
                      {!locked && (
                        <button
                          type="button"
                          disabled={!String(q.prompt || '').trim() || q.syncedToMaster}
                          title={
                            q.syncedToMaster
                              ? 'Already saved to Standard Library'
                              : 'Save to Standard Library'
                          }
                          aria-label="Save to Standard Library"
                          onClick={() => {
                            const technicalInCart = cart.filter(
                              (m) => (m.module_kind || '').toLowerCase() === 'technical',
                            );
                            if (technicalInCart.length === 0) {
                              toast({
                                title: 'Add a technical assessment to the suite first',
                                variant: 'warning',
                              });
                              return;
                            }
                            if (technicalInCart.length === 1) {
                              void syncCustomToMaster(index, technicalInCart[0].id);
                              return;
                            }
                            setSyncTargetId(technicalInCart[0].id);
                            setSyncModal({ index });
                          }}
                          className="p-1.5 rounded text-slate-500 dark:text-slate-400 hover:text-primary disabled:opacity-40"
                        >
                          <Save className="w-3.5 h-3.5" />
                        </button>
                      )}
                      <button
                        type="button"
                        disabled={locked}
                        onClick={() =>
                          setCustomQuestions((prev) => prev.filter((_, i) => i !== index))
                        }
                        className="p-1.5 rounded text-slate-500 dark:text-slate-400 hover:text-danger disabled:opacity-40"
                        aria-label="Remove question"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <select
                        disabled={locked}
                        className={`${fieldClass} h-9`}
                        value={q.question_type}
                        onChange={(e) => {
                          const next = [...customQuestions];
                          next[index] = { ...q, question_type: e.target.value };
                          setCustomQuestions(next);
                        }}
                      >
                        <option value="mcq">MCQ</option>
                        <option value="open_ended">Open</option>
                      </select>
                      <input
                        type="number"
                        min={1}
                        max={5}
                        disabled={locked}
                        className={`${fieldClass} h-9 tabular-nums`}
                        value={q.weight}
                        onChange={(e) => {
                          const next = [...customQuestions];
                          next[index] = { ...q, weight: Number(e.target.value) || 3 };
                          setCustomQuestions(next);
                        }}
                      />
                    </div>
                    {q.question_type === 'mcq' && (
                      <div className="grid grid-cols-1 gap-1.5">
                        {(q.options || ['', '', '', '']).map((opt, oi) => (
                          <input
                            key={oi}
                            disabled={locked}
                            className={`${fieldClass} h-8`}
                            placeholder={`Option ${oi + 1}`}
                            value={opt}
                            onChange={(e) => {
                              const opts = [...(q.options || [])];
                              opts[oi] = e.target.value;
                              const next = [...customQuestions];
                              next[index] = { ...q, options: opts };
                              setCustomQuestions(next);
                            }}
                          />
                        ))}
                      </div>
                    )}
                    {q.question_type === 'open_ended' && (
                      <textarea
                        rows={2}
                        disabled={locked}
                        className={`${fieldClass} resize-y`}
                        placeholder="Rubric"
                        value={q.correct_answer_or_rubric}
                        onChange={(e) => {
                          const next = [...customQuestions];
                          next[index] = { ...q, correct_answer_or_rubric: e.target.value };
                          setCustomQuestions(next);
                        }}
                      />
                    )}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>
      </div>
      </ComposerDndProvider>

      <LivePreviewDrawer
        open={previewOpen}
        onOpenChange={setPreviewOpen}
        packageTitle={title.trim() || 'Untitled suite'}
        moduleIds={cartIds}
        moduleOverrides={previewOverrides}
      />

      <Modal
        isOpen={Boolean(syncModal)}
        onClose={() => setSyncModal(null)}
        title="Save to Standard Library"
        actions={
          <>
            <Button variant="ghost" onClick={() => setSyncModal(null)}>
              Cancel
            </Button>
            <Button
              disabled={!syncTargetId}
              onClick={() => {
                if (syncModal == null) return;
                void syncCustomToMaster(syncModal.index, syncTargetId);
                setSyncModal(null);
              }}
            >
              Save
            </Button>
          </>
        }
      >
        <div className="p-4 space-y-3">
          <p className="text-sm text-slate-700 dark:text-slate-300">
            Choose which technical assessment should receive this question.
          </p>
          <select
            className={`${fieldClass} h-10`}
            value={syncTargetId}
            onChange={(e) => setSyncTargetId(e.target.value)}
            aria-label="Target assessment"
          >
            {cart
              .filter((m) => (m.module_kind || '').toLowerCase() === 'technical')
              .map((m) => (
                <option key={m.id} value={m.id}>
                  {m.title}
                </option>
              ))}
          </select>
        </div>
      </Modal>
    </div>
  );
}
