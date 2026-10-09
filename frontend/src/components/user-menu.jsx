import React from 'react';
import { Link } from 'react-router-dom';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { ChevronDown, LogOut, Settings, UserCircle } from 'lucide-react';

const ITEM_BASE =
  'flex items-center gap-2 px-2.5 py-2 rounded-md text-sm cursor-pointer outline-none select-none transition-colors duration-150';

/**
 * Resolve the label shown for the signed-in user.
 *
 * @param {string | null | undefined} fullName
 * @param {string | null | undefined} email
 * @returns {string}
 */
function displayName(fullName, email) {
  const trimmed = (fullName || '').trim();
  if (trimmed) return trimmed;
  if (email) return email.split('@')[0];
  return 'Account';
}

/**
 * Top-right account menu: identity header, Account Settings, and Sign Out.
 *
 * @param {object} props
 * @param {string | null | undefined} props.fullName
 * @param {string | null | undefined} props.email
 * @param {string} props.settingsHref
 * @param {() => void} props.onSignOut
 */
export default function UserMenu({ fullName, email, settingsHref, onSignOut }) {
  const name = displayName(fullName, email);

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger
        className="flex items-center gap-1.5 min-w-0 rounded-md px-1.5 py-1 text-muted hover:text-foreground hover:bg-surface-raised focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 data-[state=open]:bg-surface-raised data-[state=open]:text-foreground"
        aria-label="Open account menu"
      >
        <UserCircle className="w-5 h-5 shrink-0" aria-hidden="true" />
        <span className="text-xs font-medium hidden md:block truncate max-w-[12rem]">{name}</span>
        <ChevronDown className="w-3.5 h-3.5 shrink-0 hidden md:block" aria-hidden="true" />
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={8}
          className="z-50 w-64 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-1 shadow-lg"
        >
          <div className="px-2.5 py-2">
            <p className="text-sm font-semibold text-slate-900 dark:text-slate-100 truncate">
              {name}
            </p>
            {email && (
              <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400 truncate">{email}</p>
            )}
          </div>

          <DropdownMenu.Separator className="my-1 h-px bg-slate-200 dark:bg-slate-800" />

          <DropdownMenu.Item asChild>
            <Link
              to={settingsHref}
              className={`${ITEM_BASE} text-slate-700 dark:text-slate-200 data-[highlighted]:bg-slate-100 dark:data-[highlighted]:bg-slate-800`}
            >
              <Settings className="w-4 h-4 shrink-0" aria-hidden="true" />
              Account Settings
            </Link>
          </DropdownMenu.Item>

          <DropdownMenu.Item
            onSelect={onSignOut}
            className={`${ITEM_BASE} text-rose-600 dark:text-rose-400 data-[highlighted]:bg-rose-50 dark:data-[highlighted]:bg-rose-950/40`}
          >
            <LogOut className="w-4 h-4 shrink-0" aria-hidden="true" />
            Sign Out
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
