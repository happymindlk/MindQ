import React, { useEffect, useState } from 'react';
import { Building2, Palette, Mail } from 'lucide-react';
import Card from '../../components/ui/Card';
import { adminApi } from '../../lib/adminApi';

export default function Corporates() {
  const [corporate, setCorporate] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    adminApi.getCorporate()
      .then(setCorporate)
      .catch((err) => setError(err.message));
  }, []);

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-50">Corporates</h1>
        <p className="text-slate-400 mt-1">
          B2B tenant profile. Logo, brand colors, and usage quotas are planned for a later iteration.
        </p>
      </div>

      {error && (
        <p className="text-rose-400 text-sm">{error}</p>
      )}

      <Card>
        <div className="flex items-start gap-4">
          <div className="p-3 bg-indigo-500/10 rounded-xl text-indigo-400">
            <Building2 className="w-6 h-6" />
          </div>
          <div className="flex-1 space-y-4">
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-500">Organization</p>
              <p className="text-lg font-semibold text-slate-50 mt-1">{corporate?.name || '—'}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-500">Slug</p>
              <p className="font-mono text-indigo-300 mt-1">{corporate?.slug || '—'}</p>
            </div>
            <div className="flex items-center gap-2 text-sm text-slate-400">
              <Mail className="w-4 h-4" />
              Contact and branding fields are not stored in the current schema yet.
            </div>
          </div>
        </div>
      </Card>

      <Card>
        <div className="flex items-center gap-3 mb-3">
          <Palette className="w-5 h-5 text-slate-400" />
          <h2 className="font-semibold text-slate-50">White-label branding</h2>
        </div>
        <p className="text-sm text-slate-400">
          The technical report specifies custom colors and logos per corporate. This screen is the
          umbrella client view for your tenant; branding uploads will appear here when the schema is extended.
        </p>
      </Card>
    </div>
  );
}
