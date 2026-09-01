import React, { useState } from 'react';
import { Outlet, NavLink, useLocation, useNavigate } from 'react-router-dom';
import { LayoutDashboard, Building2, Library, Package, Users, Menu, UserCircle, LogOut } from 'lucide-react';
import { useAuth } from '../context/AuthContext.jsx';

export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const { user, signOut } = useAuth();

  const handleSignOut = async () => {
    await signOut();
    navigate('/admin/login', { replace: true });
  };

  const navigation = [
    { name: 'Dashboard', href: '/admin', icon: LayoutDashboard },
    { name: 'Corporates', href: '/admin/corporates', icon: Building2 },
    { name: 'Assessment Library', href: '/admin/library', icon: Library },
    { name: 'Package Builder', href: '/admin/packages/create', icon: Package },
    { name: 'HR Tracker', href: '/admin/track', icon: Users },
  ];

  const getPageTitle = () => {
    const currentNav = navigation.find(n => n.href === location.pathname);
    return currentNav ? currentNav.name : 'Admin Panel';
  };

  return (
    <div className="min-h-screen bg-slate-950 flex">
      {/* Mobile sidebar backdrop */}
      {sidebarOpen && (
        <div 
          className="fixed inset-0 z-40 bg-slate-950/80 backdrop-blur-sm lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside className={`
        fixed inset-y-0 left-0 z-50 w-64 bg-slate-900 border-r border-slate-800
        transform transition-transform duration-300 lg:translate-x-0 lg:static lg:inset-0
        ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}
      `}>
        <div className="h-16 flex items-center px-6 border-b border-slate-800">
          <div className="flex items-center gap-2 text-indigo-400">
            <div className="w-8 h-8 rounded-lg bg-indigo-500/10 flex items-center justify-center border border-indigo-500/20">
              <Package className="w-5 h-5" />
            </div>
            <span className="font-bold text-lg text-slate-50">Happy Mind</span>
          </div>
        </div>

        <nav className="p-4 space-y-1">
          {navigation.map((item) => (
            <NavLink
              key={item.name}
              to={item.href}
              end={item.href === '/admin'}
              className={({ isActive }) => `
                flex items-center gap-3 px-3 py-2.5 rounded-lg font-medium transition-colors
                ${isActive 
                  ? 'bg-indigo-500/10 text-indigo-400' 
                  : 'text-slate-400 hover:text-slate-50 hover:bg-slate-800/50'
                }
              `}
              onClick={() => setSidebarOpen(false)}
            >
              <item.icon className="w-5 h-5" />
              {item.name}
            </NavLink>
          ))}
        </nav>
      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Top Header */}
        <header className="h-16 flex items-center justify-between px-4 sm:px-6 lg:px-8 border-b border-slate-800 bg-slate-900/50 backdrop-blur-sm z-30 sticky top-0">
          <div className="flex items-center gap-4">
            <button
              className="lg:hidden text-slate-400 hover:text-slate-50"
              onClick={() => setSidebarOpen(true)}
            >
              <Menu className="w-6 h-6" />
            </button>
            <h1 className="text-xl font-semibold text-slate-50">{getPageTitle()}</h1>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 text-slate-400">
              <UserCircle className="w-8 h-8" />
              <span className="text-sm font-medium hidden sm:block">{user?.email || 'Admin'}</span>
            </div>
            <button
              onClick={handleSignOut}
              className="flex items-center gap-1.5 text-slate-400 hover:text-rose-400 text-sm font-medium ml-2"
              title="Sign out"
            >
              <LogOut className="w-5 h-5" />
              <span className="hidden sm:block">Sign out</span>
            </button>
          </div>
        </header>

        {/* Page Content */}
        <main className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
