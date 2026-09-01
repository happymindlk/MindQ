import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Clock, Cloud, LifeBuoy, ArrowRight } from 'lucide-react';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';

export default function Guidelines() {
  const navigate = useNavigate();

  return (
    <div className="w-full max-w-2xl mx-auto py-10">
      <h1 className="text-3xl font-bold text-slate-50 mb-2">Before you begin</h1>
      <p className="text-slate-400 mb-8">
        Please read these guidelines. Your answers are saved automatically while you work.
      </p>
      <div className="space-y-4 mb-10">
        <Card>
          <div className="flex gap-4">
            <Clock className="w-6 h-6 text-indigo-400 shrink-0" />
            <div>
              <h2 className="font-semibold text-slate-50">Time limits</h2>
              <p className="text-sm text-slate-400 mt-1">
                Each test may list a suggested duration. Complete sections in one sitting when possible.
              </p>
            </div>
          </div>
        </Card>
        <Card>
          <div className="flex gap-4">
            <Cloud className="w-6 h-6 text-teal-400 shrink-0" />
            <div>
              <h2 className="font-semibold text-slate-50">Autosave</h2>
              <p className="text-sm text-slate-400 mt-1">
                Responses are saved in the background every few seconds. You can close the browser and return later.
              </p>
            </div>
          </div>
        </Card>
        <Card>
          <div className="flex gap-4">
            <LifeBuoy className="w-6 h-6 text-amber-400 shrink-0" />
            <div>
              <h2 className="font-semibold text-slate-50">Support</h2>
              <p className="text-sm text-slate-400 mt-1">
                Use the technical support button if something breaks. Do not refresh mid-question unless asked to.
              </p>
            </div>
          </div>
        </Card>
      </div>
      <Button size="lg" onClick={() => navigate('/portal/dashboard')}>
        Continue to assessments
        <ArrowRight className="w-5 h-5 ml-2" />
      </Button>
    </div>
  );
}
