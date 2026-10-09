import React, { useEffect, useMemo, useState } from 'react';
import { Outlet, NavLink, Link, useLocation, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard,
  // Building2, // Corporates nav hidden for stakeholder demo
  Library,
  Layers,
  Brain,
  Users,
  Menu,
  X,
} from 'lucide-react';
import { useAuth } from '../context/useAuth';
import ToastProvider from './ui/Toast';
import ThemeToggle from './ThemeToggle';
import UserMenu from './user-menu';
import { useIdleTimer } from '../hooks/use-idle-timer';

const navigation = [
  { name: 'Dashboard', href: '/admin', icon: LayoutDashboard },
  { name: 'Standard Library', href: '/admin/library', icon: Library },
  { name: 'Suite Builder', href: '/admin/packages/create', icon: Layers },
  { name: 'Assessment History', href: '/admin/history', icon: Users },
];

const SETTINGS_HREF = '/admin/settings';
const SIDEBAR_ID = 'admin-sidebar';

function resolveShellTitle(pathname) {
  if (pathname.startsWith(SETTINGS_HREF)) {
    return 'Account Settings';
  }
  if (pathname.startsWith('/admin/candidates/')) {
    return 'Candidate Report';
  }
  if (pathname.startsWith('/admin/history') || pathname.startsWith('/track/') || pathname === '/admin/track' || pathname === '/admin/candidates') {
    return 'Assessment History';
  }
  const match = navigation.find((n) =>
    n.href === '/admin' ? pathname === '/admin' : pathname.startsWith(n.href),
  );
  return match?.name ?? 'Admin';
}

function BrandLink() {
  return (
    <Link
      to="/admin"
      aria-label="MindQ home"
      className="flex items-center gap-2 min-w-0 rounded-md focus-visible:ring-2 focus-visible:ring-primary"
    >
      <div className="w-7 h-7 rounded-md bg-indigo-600 flex items-center justify-center shrink-0">
        <Brain className="w-3.5 h-3.5 text-white" aria-hidden />
      </div>
      <span className="font-semibold text-sm text-foreground truncate">MindQ</span>
    </Link>
  );
}

export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const { user, profile, signOut, lockSession } = useAuth();

  useIdleTimer({ onIdle: lockSession });

  useEffect(() => {
    setSidebarOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!sidebarOpen) return undefined;
    const onKeyDown = (event) => {
      if (event.key === 'Escape') setSidebarOpen(false);
    };
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    window.addEventListener('keydown', onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [sidebarOpen]);

  const shellTitle = useMemo(
    () => resolveShellTitle(location.pathname),
    [location.pathname],
  );

  const handleSignOut = async () => {
    await signOut();
    navigate('/admin/login', { replace: true });
  };

  return (
    <ToastProvider>
      <div className="min-h-screen bg-canvas flex text-foreground">
        {sidebarOpen && (
          <button
            type="button"
            className="fixed inset-0 z-40 bg-black/40 lg:hidden"
            aria-label="Close navigation"
            onClick={() => setSidebarOpen(false)}
          />
        )}

        <aside
          id={SIDEBAR_ID}
          aria-label="Primary navigation"
          className={`
            fixed inset-y-0 left-0 z-50 w-56 shrink-0 bg-surface border-r border-border
            transform transition-transform duration-200 lg:translate-x-0
            lg:sticky lg:top-0 lg:h-screen lg:overflow-y-auto
            ${sidebarOpen ? 'translate-x-0 shadow-xl' : '-translate-x-full'}
          `}
        >
          <div className="h-12 flex items-center justify-between px-3 border-b border-border">
            <BrandLink />

            <button
              type="button"
              className="lg:hidden p-1 rounded-md text-muted hover:text-foreground"
              onClick={() => setSidebarOpen(false)}
              aria-label="Close sidebar"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <nav className="p-2 space-y-0.5">
            {navigation.map((item) => (
              <NavLink
                key={item.name}
                to={item.href}
                end={item.href === '/admin'}
                className={({ isActive }) => `
                  flex items-center gap-2.5 px-2.5 py-2 rounded-md text-sm font-medium transition-colors duration-150
                  focus-visible:ring-2 focus-visible:ring-primary
                  ${
                    isActive
                      ? 'bg-indigo-50 text-indigo-700 border-r-2 border-indigo-600 dark:bg-indigo-950/40 dark:text-indigo-300 dark:border-indigo-400'
                      : 'text-muted hover:text-foreground hover:bg-surface-raised'
                  }
                `}
                onClick={() => setSidebarOpen(false)}
              >
                <item.icon className="w-4 h-4 shrink-0" />
                {item.name}
              </NavLink>
            ))}
          </nav>
        </aside>

        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          <header className="h-12 flex items-center justify-between gap-3 px-3 sm:px-4 border-b border-border bg-surface z-30 sticky top-0">
            <div className="flex items-center gap-2 min-w-0">
              <button
                type="button"
                className="lg:hidden text-muted hover:text-foreground p-1 rounded-md focus-visible:ring-2 focus-visible:ring-primary"
                onClick={() => setSidebarOpen(true)}
                aria-label="Open navigation"
                aria-expanded={sidebarOpen}
                aria-controls={SIDEBAR_ID}
              >
                <Menu className="w-5 h-5" />
              </button>
              <div className="lg:hidden">
                <BrandLink />
              </div>
              <p className="text-xs font-medium text-muted truncate hidden sm:block">
                {shellTitle}
              </p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <ThemeToggle />
              <UserMenu
                fullName={profile?.full_name}
                email={user?.email}
                settingsHref={SETTINGS_HREF}
                onSignOut={handleSignOut}
              />
            </div>
          </header>

          <main className="flex-1 overflow-y-auto p-3 sm:p-4">
            <Outlet />
          </main>
        </div>
      </div>
    </ToastProvider>
  );
}
