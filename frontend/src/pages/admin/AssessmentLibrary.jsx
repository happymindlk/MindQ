import React, { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Brain, Code2, Search } from 'lucide-react';
import Button from '../../components/ui/Button';
import Input from '../../components/ui/Input';
import PageHeader from '../../components/ui/PageHeader';
import Modal from '../../components/ui/Modal';
import { AssessmentBuilderWorkspace } from '../../features/assessment-builder/components/assessment-builder-workspace';
import { useModuleLibrary } from '../../features/assessment-builder/hooks/use-module-library';

const TABS = [
  { id: 'all', label: 'All', cta: '+ New Assessment' },
  { id: 'psychometric', label: 'Psychometric', cta: '+ New Psychometric' },
  { id: 'technical', label: 'Technical', cta: '+ New Technical' },
];

const CATEGORY_OPTIONS = [
  {
    id: 'psychometric',
    label: 'Psychometric Assessment',
    description: 'Behavioral, cognitive, and personality modules.',
    icon: Brain,
  },
  {
    id: 'technical',
    label: 'Technical Assessment',
    description: 'Role-specific skills, MCQ, and open-ended tasks.',
    icon: Code2,
  },
];

export default function AssessmentLibrary() {
  const navigate = useNavigate();
  const library = useModuleLibrary();
  const [search, setSearch] = useState('');
  const [activeTab, setActiveTab] = useState('all');
  const [typePickerOpen, setTypePickerOpen] = useState(false);
  const [createDraft, setCreateDraft] = useState(null);

  const tabCounts = useMemo(() => {
    const counts = { all: library.modules.length, psychometric: 0, technical: 0 };
    library.modules.forEach((m) => {
      if (m.moduleKind in counts) counts[m.moduleKind] += 1;
    });
    return counts;
  }, [library.modules]);

  const activeTabConfig = TABS.find((t) => t.id === activeTab) ?? TABS[0];

  const openCreate = (kind) => {
    setTypePickerOpen(false);
    setCreateDraft({ kind, category: kind === 'psychometric' ? 'behavioral' : null });
  };

  const onPrimaryCta = () => {
    if (activeTab === 'all') {
      setTypePickerOpen(true);
      return;
    }
    openCreate(activeTab);
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Standard Library"
        actions={
          <div className="flex items-center gap-2 w-full sm:w-auto">
            <Input
              icon={Search}
              placeholder="Search assessments"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full sm:w-56"
              aria-label="Search assessments"
            />
            <Button
              size="sm"
              variant="secondary"
              onClick={() => navigate('/admin/packages/create')}
              className="shrink-0"
            >
              Build Suite
            </Button>
            <Button size="sm" onClick={onPrimaryCta} className="shrink-0">
              {activeTabConfig.cta}
            </Button>
          </div>
        }
      />

      <div
        role="tablist"
        aria-label="Filter templates by category"
        className="flex items-center gap-1 border-b border-neutral-800"
      >
        {TABS.map((tab) => {
          const selected = tab.id === activeTab;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={selected}
              onClick={() => setActiveTab(tab.id)}
              className={`-mb-px inline-flex items-center gap-2 px-3 py-2 text-sm border-b-2 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded-t-md ${
                selected
                  ? 'border-primary text-foreground font-semibold'
                  : 'border-transparent text-neutral-400 hover:text-foreground'
              }`}
            >
              {tab.label}
              <span className="font-mono tabular-nums text-[11px] text-neutral-500">
                {tabCounts[tab.id] ?? 0}
              </span>
            </button>
          );
        })}
      </div>

      <AssessmentBuilderWorkspace
        library={library}
        filter={activeTab}
        search={search}
        createDraft={createDraft}
        onCreateDraftChange={setCreateDraft}
      />

      <Modal
        isOpen={typePickerOpen}
        onClose={() => setTypePickerOpen(false)}
        title="New Assessment"
        contentClassName="bg-neutral-900 border border-neutral-800 text-neutral-100"
      >
        <div className="grid gap-2 sm:grid-cols-2">
          {CATEGORY_OPTIONS.map(({ id, label, description, icon: Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => openCreate(id)}
              className="flex flex-col items-start gap-2 rounded-lg border border-neutral-800 bg-canvas p-4 text-left transition-colors hover:border-primary hover:bg-surface-raised focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              <Icon className="w-5 h-5 text-primary" aria-hidden />
              <span className="text-sm font-semibold text-foreground">{label}</span>
              <span className="text-xs text-neutral-400 leading-relaxed">{description}</span>
            </button>
          ))}
        </div>
      </Modal>
    </div>
  );
}
