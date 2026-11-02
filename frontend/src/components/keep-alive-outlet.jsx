import React, { useLayoutEffect, useRef, useState } from 'react';
import { useLocation, useOutlet } from 'react-router-dom';
import { ADMIN_KEEP_PATTERNS, resolveKeepAliveKey } from './keep-alive-routes';

/**
 * Preserve visited tab trees with CSS hide/show so switching back is instant.
 *
 * @param {{ patterns?: { key: string, path: string, end: boolean }[] }} [props]
 */
export default function KeepAliveOutlet({ patterns = ADMIN_KEEP_PATTERNS }) {
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
