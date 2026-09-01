import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Search, Copy, Users, Link2 } from 'lucide-react';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import Badge from '../../components/ui/Badge';
import Input from '../../components/ui/Input';
import { adminApi } from '../../lib/adminApi';

export default function AssessmentLibrary() {
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [packages, setPackages] = useState([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    adminApi.getPackages()
      .then((data) => setPackages(data || []))
      .catch((err) => console.error(err))
      .finally(() => setIsLoading(false));
  }, []);

  const handleCopyCode = (code) => {
    navigator.clipboard.writeText(code);
  };

  const portalLink = (code) => `${window.location.origin}/portal?code=${encodeURIComponent(code)}`;

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-50">Assessment Library</h1>
          <p className="text-slate-400 mt-1">
            Packages bundling psychometric, technical, and operational tests (max 6 per package).
          </p>
        </div>
        <div className="flex items-center gap-3 w-full sm:w-auto">
          <Input
            icon={Search}
            placeholder="Search packages..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full sm:w-64"
          />
          <Button onClick={() => navigate('/admin/packages/create')} className="shrink-0">
            <Plus className="w-4 h-4 mr-2" />
            Package Builder
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {packages
          .filter((pkg) =>
            pkg.title.toLowerCase().includes(search.toLowerCase())
            || pkg.access_code.toLowerCase().includes(search.toLowerCase())
          )
          .map((pkg) => (
            <Card key={pkg.id} variant="elevated" className="flex flex-col">
              <div className="flex justify-between items-start mb-4">
                <Badge variant={pkg.is_active ? 'success' : 'neutral'}>
                  {pkg.is_active ? 'Active' : 'Archived'}
                </Badge>
                <button
                  className="p-1.5 text-slate-400 hover:text-indigo-400 hover:bg-slate-800 rounded-md"
                  title="Open HR tracker"
                  onClick={() => navigate(`/track/${pkg.id}`)}
                >
                  <Link2 className="w-4 h-4" />
                </button>
              </div>
              <h3 className="text-lg font-semibold text-slate-50 mb-1">{pkg.title}</h3>
              <p className="text-sm text-slate-400 line-clamp-2 mb-4">{pkg.description || 'No job description attached.'}</p>
              <div className="flex items-center justify-between mt-auto pt-4 border-t border-slate-800">
                <div className="flex items-center gap-2 bg-slate-900/50 px-3 py-1.5 rounded-lg border border-slate-700">
                  <span className="text-sm font-mono text-indigo-300">{pkg.access_code}</span>
                  <button onClick={() => handleCopyCode(pkg.access_code)} className="text-slate-400 hover:text-slate-50">
                    <Copy className="w-3.5 h-3.5" />
                  </button>
                </div>
                <div className="flex items-center text-sm text-slate-400">
                  <Users className="w-4 h-4 mr-1" />
                  {pkg.candidate_count ?? 0}
                </div>
              </div>
              <p className="text-xs text-slate-600 mt-3 truncate" title={portalLink(pkg.access_code)}>
                Candidate link uses ?code=
              </p>
            </Card>
          ))}
      </div>
      {packages.length === 0 && !isLoading && (
        <div className="text-center py-12 text-slate-500 italic">
          No packages yet. Open Package Builder to compose one.
        </div>
      )}
      {isLoading && <div className="text-center py-12 text-slate-500">Loading library...</div>}
    </div>
  );
}
