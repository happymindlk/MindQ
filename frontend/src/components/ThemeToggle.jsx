import React from 'react';
import { Moon, Sun } from 'lucide-react';
import { useTheme } from '../context/use-theme';

/**
 * Minimal sun/moon control for the admin shell header.
 */
export default function ThemeToggle({ className = '' }) {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === 'dark';

  return (
    <button
      type="button"
      onClick={toggleTheme}
      className={`
        inline-flex items-center justify-center h-8 w-8 rounded-md
        text-muted hover:text-foreground hover:bg-surface-raised
        focus-visible:ring-2 focus-visible:ring-primary
        transition-colors duration-150
        ${className}
      `}
      aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      title={isDark ? 'Light mode' : 'Dark mode'}
    >
      {isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
    </button>
  );
}
