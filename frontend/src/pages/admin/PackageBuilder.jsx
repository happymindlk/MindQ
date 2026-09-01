import React, { useState } from 'react';
import { Plus, Trash2, GripVertical, Check, Copy, ArrowRight, X } from 'lucide-react';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import Input from '../../components/ui/Input';
import Modal from '../../components/ui/Modal';
import { adminApi } from '../../lib/adminApi';

export default function PackageBuilder() {
  const [title, setTitle] = useState('');
  const [jobDescription, setJobDescription] = useState('');
  const [tests, setTests] = useState([]);
  
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [generatedCode, setGeneratedCode] = useState(null);

  const addTest = () => {
    if (tests.length >= 6) return;
    setTests([...tests, { id: Date.now(), title: '', description: '', questions: [] }]);
  };

  const removeTest = (testId) => {
    setTests(tests.filter(t => t.id !== testId));
  };

  const addQuestion = (testId) => {
    setTests(tests.map(test => {
      if (test.id === testId) {
        return {
          ...test,
          questions: [...test.questions, { id: Date.now(), text: '', type: 'mcq', options: [''] }]
        };
      }
      return test;
    }));
  };

  const removeQuestion = (testId, questionId) => {
    setTests(tests.map(test => {
      if (test.id === testId) {
        return { ...test, questions: test.questions.filter(q => q.id !== questionId) };
      }
      return test;
    }));
  };

  const handleSave = async () => {
    if (!title || tests.length === 0) return;
    setIsSubmitting(true);
    try {
      // The tenant (corporate_id) comes from the signed-in HR user's JWT, so we
      // no longer send an organization name from the client.
      const data = {
        title,
        description: jobDescription,
        tests: tests.slice(0, 6).map((t) => ({
          title: t.title,
          description: t.description || '',
          questions: t.questions.map((q, qIdx) => ({
            id: `q-${qIdx}-${q.text.toLowerCase().replace(/[^a-z0-9]/g, '-').slice(0, 15)}`,
            text: q.text,
            type: q.type,
            options: q.options || [],
          })),
        })),
      };
      const res = await adminApi.createPackage(data);
      setGeneratedCode(res.access_code);
    } catch (error) {
      console.error(error);
      alert('Failed to save package: ' + error.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(generatedCode);
  };

  return (
    <div className="max-w-5xl mx-auto pb-20">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-slate-50">Package Builder</h1>
          <p className="text-slate-400 mt-1">
            Structure sections (Likert, MCQ, open-ended), attach a job description, max 6 assessments.
          </p>
        </div>
        <Button onClick={handleSave} isLoading={isSubmitting} disabled={tests.length === 0 || !title}>
          Save & Generate Code
        </Button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 space-y-6">
          <Card>
            <div className="space-y-4">
              <Input 
                label="Package Title" 
                placeholder="e.g., Senior Developer Assessment" 
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1.5">Job Description (for AI grading)</label>
                <textarea
                  className="w-full rounded-lg bg-slate-900 border border-slate-700 text-slate-50 text-sm focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 p-3 h-24 resize-none"
                  placeholder="Paste the role JD. Scoring against this JD is not wired to Gemini yet; the text is stored on the package."
                  value={jobDescription}
                  onChange={(e) => setJobDescription(e.target.value)}
                />
              </div>
            </div>
          </Card>

          {/* Tests List */}
          <div className="space-y-6">
            {tests.map((test, index) => (
              <Card key={test.id} className="border-l-4 border-l-indigo-500">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-lg font-medium text-slate-50">Test {index + 1}</h3>
                  <button onClick={() => removeTest(test.id)} className="text-rose-400 hover:text-rose-300 p-1">
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
                
                <div className="space-y-4 mb-6">
                  <Input placeholder="Test Title" value={test.title} onChange={e => {
                    const newTests = [...tests];
                    newTests[index].title = e.target.value;
                    setTests(newTests);
                  }}/>
                </div>

                <div className="space-y-4">
                  <h4 className="text-sm font-medium text-slate-400">Questions</h4>
                  {test.questions.map((q, qIndex) => (
                    <div key={q.id} className="flex gap-3 bg-slate-900/50 p-4 rounded-lg border border-slate-800">
                      <GripVertical className="w-5 h-5 text-slate-600 shrink-0 mt-2" />
                      <div className="flex-1 space-y-3">
                        <Input placeholder="Question text..." value={q.text} onChange={e => {
                           const newTests = [...tests];
                           newTests[index].questions[qIndex].text = e.target.value;
                           setTests(newTests);
                        }}/>
                        <select 
                          className="w-full sm:w-48 rounded-lg bg-slate-900 border border-slate-700 text-slate-50 text-sm p-2"
                          value={q.type}
                          onChange={e => {
                            const newTests = [...tests];
                            newTests[index].questions[qIndex].type = e.target.value;
                            if (e.target.value === 'mcq' && (!q.options || q.options.length === 0)) {
                              newTests[index].questions[qIndex].options = ['Option 1', 'Option 2'];
                            }
                            setTests(newTests);
                          }}
                        >
                          <option value="mcq">Multiple Choice</option>
                          <option value="likert">Likert Scale</option>
                          <option value="open">Open Ended</option>
                        </select>

                        {q.type === 'mcq' && (
                          <div className="space-y-2 pl-4 border-l-2 border-slate-700 mt-2">
                            <label className="text-xs text-slate-400 block font-medium">MCQ Options</label>
                            {(q.options || []).map((opt, optIndex) => (
                              <div key={optIndex} className="flex gap-2 items-center">
                                <input
                                  type="text"
                                  className="flex-1 rounded-md bg-slate-950 border border-slate-750 text-slate-50 text-xs p-1.5 focus:ring-1 focus:ring-indigo-500"
                                  placeholder={`Option ${optIndex + 1}`}
                                  value={opt}
                                  onChange={e => {
                                    const newTests = [...tests];
                                    newTests[index].questions[qIndex].options[optIndex] = e.target.value;
                                    setTests(newTests);
                                  }}
                                />
                                <button
                                  type="button"
                                  className="text-rose-400 hover:text-rose-300 text-xs px-1"
                                  onClick={() => {
                                    const newTests = [...tests];
                                    newTests[index].questions[qIndex].options = q.options.filter((_, oIdx) => oIdx !== optIndex);
                                    setTests(newTests);
                                  }}
                                >
                                  Remove
                                </button>
                              </div>
                            ))}
                            <button
                              type="button"
                              className="text-xs text-indigo-400 hover:text-indigo-300 font-medium"
                              onClick={() => {
                                const newTests = [...tests];
                                if (!newTests[index].questions[qIndex].options) {
                                  newTests[index].questions[qIndex].options = [];
                                }
                                newTests[index].questions[qIndex].options.push('');
                                setTests(newTests);
                              }}
                            >
                              + Add Option
                            </button>
                          </div>
                        )}
                      </div>
                      <button onClick={() => removeQuestion(test.id, q.id)} className="text-slate-500 hover:text-rose-400 p-1 shrink-0 h-fit">
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                  ))}
                  <Button variant="secondary" size="sm" onClick={() => addQuestion(test.id)}>
                    <Plus className="w-4 h-4 mr-2" /> Add Question
                  </Button>
                </div>
              </Card>
            ))}
          </div>

          <Button
            variant="ghost"
            className="w-full border border-dashed border-slate-700 py-6"
            onClick={addTest}
            disabled={tests.length >= 6}
          >
            <Plus className="w-5 h-5 mr-2" />
            {tests.length >= 6 ? 'Maximum 6 assessments per package' : 'Add New Test Section'}
          </Button>
        </div>

        {/* Preview Panel */}
        <div className="lg:col-span-1">
          <div className="sticky top-24">
            <Card variant="elevated">
              <h3 className="font-semibold text-slate-50 border-b border-slate-800 pb-3 mb-4">Package Summary</h3>
              <div className="space-y-4 text-sm">
                <div>
                  <span className="text-slate-400 block mb-1">Title</span>
                  <span className="text-slate-200">{title || 'Untitled Package'}</span>
                </div>
                <div className="pt-4 border-t border-slate-800">
                  <span className="text-slate-400 block mb-2">Content ({tests.length}/6)</span>
                  <ul className="space-y-2">
                    {tests.map((t, i) => (
                      <li key={t.id} className="flex items-center justify-between text-slate-300">
                        <span className="truncate pr-2">{t.title || `Test ${i + 1}`}</span>
                        <span className="shrink-0 bg-slate-800 px-2 py-0.5 rounded-full text-xs">{t.questions.length} Qs</span>
                      </li>
                    ))}
                    {tests.length === 0 && (
                      <li className="text-slate-500 italic">No tests added yet</li>
                    )}
                  </ul>
                </div>
              </div>
            </Card>
          </div>
        </div>
      </div>

      <Modal 
        isOpen={!!generatedCode} 
        onClose={() => setGeneratedCode(null)}
        title="Package Created Successfully!"
        actions={
          <Button onClick={() => setGeneratedCode(null)}>Done</Button>
        }
      >
        <div className="text-center py-6">
          <div className="w-16 h-16 bg-emerald-500/20 rounded-full flex items-center justify-center mx-auto mb-4">
            <Check className="w-8 h-8 text-emerald-400" />
          </div>
          <p className="text-slate-300 mb-6">
            Share this access code with candidates so they can begin the assessment.
          </p>
          <div className="flex items-center justify-center gap-3">
            <code className="px-4 py-3 bg-slate-950 rounded-lg text-2xl font-mono text-indigo-400 border border-slate-800">
              {generatedCode}
            </code>
            <Button variant="secondary" onClick={handleCopy} className="p-3">
              <Copy className="w-5 h-5" />
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
