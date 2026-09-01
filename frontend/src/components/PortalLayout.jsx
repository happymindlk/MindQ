import React from 'react';
import { Outlet } from 'react-router-dom';
import { Package } from 'lucide-react';
import SupportModal from './SupportModal';

export default function PortalLayout() {
  return (
    <div className="min-h-screen bg-slate-950 flex flex-col relative overflow-hidden">
      {/* Decorative background gradients */}
      <div className="absolute top-0 inset-x-0 h-64 bg-gradient-to-b from-indigo-900/20 to-transparent pointer-events-none" />
      <div className="absolute -top-40 -right-40 w-96 h-96 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute top-1/4 -left-40 w-96 h-96 bg-teal-500/10 rounded-full blur-3xl pointer-events-none" />

      {/* Header */}
      <header className="relative z-10 border-b border-slate-800/50 bg-slate-900/30 backdrop-blur-md">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2 text-indigo-400">
            <div className="w-8 h-8 rounded-lg bg-indigo-500/10 flex items-center justify-center border border-indigo-500/20">
              <Package className="w-5 h-5" />
            </div>
            <span className="font-bold text-lg text-slate-50">Happy Mind</span>
          </div>
          <div className="text-sm text-slate-400">
            Assessment Portal
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="relative z-10 flex-1 flex flex-col items-center p-4 sm:p-6">
        <div className="w-full max-w-4xl flex-1 flex flex-col">
          <Outlet />
        </div>
      </main>

      <SupportModal />
    </div>
  );
}
