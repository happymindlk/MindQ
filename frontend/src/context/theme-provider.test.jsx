import React from 'react';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ThemeProvider } from './ThemeProvider';
import ThemeToggle from '../components/ThemeToggle';

function renderWithTheme() {
  return render(
    <ThemeProvider>
      <ThemeToggle />
    </ThemeProvider>,
  );
}

describe('ThemeProvider', () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.className = '';
    document.documentElement.style.colorScheme = '';
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('honours a stored light preference even when <html> starts with the dark class', () => {
    window.localStorage.setItem('theme', 'light');
    document.documentElement.classList.add('dark');

    renderWithTheme();

    expect(document.documentElement.classList.contains('dark')).toBe(false);
    expect(document.documentElement.style.colorScheme).toBe('light');
    expect(window.localStorage.getItem('theme')).toBe('light');
    expect(screen.getByRole('button', { name: 'Switch to dark mode' })).toBeInTheDocument();
  });

  it('defaults to dark when nothing (or garbage) is stored', () => {
    window.localStorage.setItem('theme', 'sepia');
    renderWithTheme();
    expect(document.documentElement.classList.contains('dark')).toBe(true);
  });

  it('toggles and persists the preference', async () => {
    const user = userEvent.setup();
    renderWithTheme();

    await user.click(screen.getByRole('button', { name: 'Switch to light mode' }));
    expect(document.documentElement.classList.contains('dark')).toBe(false);
    expect(window.localStorage.getItem('theme')).toBe('light');

    await user.click(screen.getByRole('button', { name: 'Switch to dark mode' }));
    expect(document.documentElement.classList.contains('dark')).toBe(true);
    expect(window.localStorage.getItem('theme')).toBe('dark');
  });

  it('mirrors theme changes made in another tab', () => {
    renderWithTheme();
    expect(document.documentElement.classList.contains('dark')).toBe(true);

    act(() => {
      window.dispatchEvent(new StorageEvent('storage', { key: 'theme', newValue: 'light' }));
    });
    expect(document.documentElement.classList.contains('dark')).toBe(false);

    act(() => {
      window.dispatchEvent(new StorageEvent('storage', { key: 'theme', newValue: 'neon' }));
    });
    expect(document.documentElement.classList.contains('dark')).toBe(false);
  });

  it('still applies the theme when localStorage is unavailable', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('SecurityError');
    });
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const user = userEvent.setup();

    renderWithTheme();
    expect(document.documentElement.classList.contains('dark')).toBe(true);

    await user.click(screen.getByRole('button', { name: 'Switch to light mode' }));
    expect(document.documentElement.classList.contains('dark')).toBe(false);
  });
});
