import React, { useLayoutEffect, useRef, useState } from 'react';
import { matchPath, useLocation, useOutlet } from 'react-router-dom';

/**
 * Primary admin nav routes that are safe to keep mounted across tab switches.
 * Parameterized detail/edit routes are excluded so they remount cleanly.
 */
const ADMIN_KEEP = [
  { key: 'admin-home', path: '/admin', end: true },
  { key: 'admin-home', path: '/admin/dashboard', end: true },
  { key: 'admin-library', path: '/admin/library', end: false },
  { key: 'admin-suite-create', path: '/admin/packages/create', end: true },
  { key: 'admin-history', path: '/admin/history', end: false },
];

const PORTAL_KEEP = [
  { key: 'portal-dashboard', path: '/portal/dashboard', end: true },
  { key: 'portal-guidelines', path: '/portal/guidelines', end: true },
];

const CLIENT_KEEP = [{ key: 'client-dashboard', path: '/client/dashboard', end: true }];

/**
 * @param {string} pathname
 * @param {{ key: string, path: string, end: boolean }[]} patterns
 * @returns {string | null}
 */
export function resolveKeepAliveKey(pathname, patterns) {
  for (const pattern of patterns) {
    if (matchPath({ path: pattern.path, end: pattern.end }, pathname)) {
      return pattern.key;
    }
  }
  return null;
}

/**
 * Preserve visited tab trees with CSS hide/show so switching back is instant.
 *
 * @param {{ patterns?: { key: string, path: string, end: boolean }[] }} [props]
 */
export default function KeepAliveOutlet({ patterns = ADMIN_KEEP }) {
  const outlet = useOutlet();
  const { pathname } = useLocation();
  const keepKey = resolveKeepAliveKey(pathname, patterns);
  const cacheRef = useRef(new Map());
  const [, setVersion] = useState(0);

  useLayoutEffect(() => {
    if (keepKey == null || outlet == null) return;
    // Freeze the first mounted tree for this key; later visits reuse it so
    // local UI state survives while useParams/useLocation still update.
    if (!cacheRef.current.has(keepKey)) {
      cacheRef.current.set(keepKey, outlet);
      setVersion((v) => v + 1);
    }
  }, [keepKey, outlet]);

  const cached = keepKey != null ? cacheRef.current.get(keepKey) : null;

  return (
    <>
      {[...cacheRef.current.entries()].map(([key, node]) => {
        const active = key === keepKey;
        return (
          <div
            key={key}
            hidden={!active}
            style={{ display: active ? 'contents' : 'none' }}
            aria-hidden={active ? undefined : true}
          >
            {node}
          </div>
        );
      })}
      {keepKey == null ? outlet : null}
      {keepKey != null && !cached ? outlet : null}
    </>
  );
}

export const ADMIN_KEEP_PATTERNS = ADMIN_KEEP;
export const PORTAL_KEEP_PATTERNS = PORTAL_KEEP;
export const CLIENT_KEEP_PATTERNS = CLIENT_KEEP;
