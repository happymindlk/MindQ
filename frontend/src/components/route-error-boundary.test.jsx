import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import RouteErrorBoundary from './route-error-boundary';

const crash = { enabled: true };

function Crashing() {
  if (crash.enabled) throw new Error('rows.map is not a function');
  return <p>Recovered page</p>;
}

function Shell() {
  const navigate = useNavigate();
  return (
    <div>
      <nav>
        <button type="button" onClick={() => navigate('/healthy')}>
          Go healthy
        </button>
      </nav>
      <RouteErrorBoundary>
        <Routes>
          <Route path="/broken" element={<Crashing />} />
          <Route path="/healthy" element={<p>Healthy page</p>} />
        </Routes>
      </RouteErrorBoundary>
    </div>
  );
}

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Shell />
    </MemoryRouter>,
  );
}

describe('RouteErrorBoundary', () => {
  afterEach(() => {
    crash.enabled = true;
    vi.restoreAllMocks();
  });

  it('keeps the surrounding shell mounted when a page throws during render', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    renderAt('/broken');
    expect(screen.getByRole('alert')).toHaveTextContent('This page failed to load');
    expect(screen.getByRole('button', { name: 'Go healthy' })).toBeInTheDocument();
  });

  it('resets when the user navigates to another route', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    renderAt('/broken');
    await userEvent.click(screen.getByRole('button', { name: 'Go healthy' }));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByText('Healthy page')).toBeInTheDocument();
  });

  it('re-renders the page on "Try again" once the fault clears', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    renderAt('/broken');
    crash.enabled = false;
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(screen.getByText('Recovered page')).toBeInTheDocument();
  });
});
