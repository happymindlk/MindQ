import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Building2, Users, CheckCircle, Activity } from 'lucide-react';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import { adminApi, candidateStatus } from '../../lib/adminApi';

export default function Dashboard() {
  const navigate = useNavigate();
  const [packages, setPackages] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [corporate, setCorporate] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    async function loadData() {
      try {
        const [pkgs, cands, corp] = await Promise.all([
          adminApi.getPackages(),
          adminApi.getCandidates(),
          adminApi.getCorporate().catch(() => null),
        ]);
        setPackages(pkgs || []);
        setCandidates(cands || []);
        setCorporate(corp);
      } catch (err) {
        console.error('Failed to load dashboard data:', err);
      } finally {
        setIsLoading(false);
      }
    }
    loadData();
  }, []);

  const invited = candidates.length;
  const inProgress = candidates.filter((c) => candidateStatus(c) === 'in_progress').length;
  const completed = candidates.filter((c) => candidateStatus(c) === 'completed').length;
  const completionRate = invited > 0 ? `${Math.round((completed / invited) * 100)}%` : '0%';

  const stats = [
    { name: 'Active corporate account', value: corporate?.name ? 1 : 0, icon: Building2, change: corporate?.name || 'Link HR user to a corporate' },
    { name: 'Active candidate sessions', value: inProgress, icon: Activity, change: 'In progress' },
    { name: 'Completed sessions', value: completed, icon: CheckCircle, change: 'Finished all tests' },
    { name: 'Completion rate', value: completionRate, icon: Users, change: `${completed} / ${invited} registered` },
  ];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {stats.map((stat) => (
          <Card key={stat.name} className="flex flex-col">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-sm font-medium text-slate-400">{stat.name}</p>
                <p className="mt-2 text-3xl font-bold text-slate-50">{stat.value}</p>
              </div>
              <div className="p-3 bg-indigo-500/10 rounded-xl">
                <stat.icon className="w-5 h-5 text-indigo-400" />
              </div>
            </div>
            <div className="mt-4 text-sm text-slate-400">{stat.change}</div>
          </Card>
        ))}
      </div>

      <Card className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-50">Assessment operations</h2>
          <p className="text-sm text-slate-400 mt-1">
            {isLoading ? 'Loading…' : `${packages.length} package(s) in the library.`}
          </p>
        </div>
        <div className="flex gap-3">
          <Button variant="secondary" onClick={() => navigate('/admin/library')}>Library</Button>
          <Button onClick={() => navigate('/admin/packages/create')}>Package Builder</Button>
        </div>
      </Card>
    </div>
  );
}
