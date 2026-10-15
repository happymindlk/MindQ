import React, { useMemo, useState } from 'react';
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react';

/**
 * Compact sortable data table with sticky header.
 *
 * @param {Array<{ id: string, header: string, accessor?: (row) => any, cell?: (row) => React.ReactNode, sortable?: boolean, align?: 'left'|'right', tabular?: boolean, className?: string }>} columns
 * @param {Array<object>} data
 * @param {(row) => string|number} getRowId
 * @param {(row) => void} [onRowClick]
 * @param {React.ReactNode} [empty]
 */
export default function DataTable({
  columns = [],
  data = [],
  getRowId = (row) => row.id,
  onRowClick,
  empty = null,
  className = '',
}) {
  const [sort, setSort] = useState({ id: null, dir: 'asc' });

  const sorted = useMemo(() => {
    if (!sort.id) return data;
    const col = columns.find((c) => c.id === sort.id);
    if (!col) return data;
    const getVal = col.accessor ?? ((row) => row[col.id]);
    const copy = [...data];
    copy.sort((a, b) => {
      const av = getVal(a);
      const bv = getVal(b);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === 'number' && typeof bv === 'number') {
        return sort.dir === 'asc' ? av - bv : bv - av;
      }
      const as = String(av).toLowerCase();
      const bs = String(bv).toLowerCase();
      if (as < bs) return sort.dir === 'asc' ? -1 : 1;
      if (as > bs) return sort.dir === 'asc' ? 1 : -1;
      return 0;
    });
    return copy;
  }, [columns, data, sort]);

  const toggleSort = (col) => {
    if (col.sortable === false) return;
    setSort((prev) => {
      if (prev.id !== col.id) return { id: col.id, dir: 'asc' };
      if (prev.dir === 'asc') return { id: col.id, dir: 'desc' };
      return { id: null, dir: 'asc' };
    });
  };

  if (!data.length && empty) {
    return empty;
  }

  return (
    <div className={`border border-slate-200 dark:border-neutral-800 rounded-lg overflow-hidden bg-surface ${className}`}>
      <div className="overflow-x-auto max-h-[min(70vh,720px)]">
        <table className="w-full text-left text-sm border-collapse">
          <thead className="sticky top-0 z-10 bg-surface-raised text-neutral-500 dark:text-neutral-400 border-b border-slate-200 dark:border-neutral-800">
            <tr>
              {columns.map((col) => {
                const align = col.align === 'right' ? 'text-right' : 'text-left';
                const sortable = col.sortable !== false;
                const active = sort.id === col.id;
                return (
                  <th
                    key={col.id}
                    scope="col"
                    className={`px-3 py-2 font-medium text-xs uppercase tracking-wider whitespace-nowrap ${align} ${col.className ?? ''}`}
                  >
                    {sortable ? (
                      <button
                        type="button"
                        onClick={() => toggleSort(col)}
                        className="inline-flex items-center gap-1 hover:text-foreground focus-visible:ring-2 focus-visible:ring-primary rounded"
                      >
                        {col.header}
                        {active && sort.dir === 'asc' && <ArrowUp className="w-3 h-3" />}
                        {active && sort.dir === 'desc' && <ArrowDown className="w-3 h-3" />}
                        {!active && <ArrowUpDown className="w-3 h-3 opacity-40" />}
                      </button>
                    ) : (
                      col.header
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 dark:divide-neutral-800 text-muted">
            {sorted.map((row) => {
              const rowId = getRowId(row);
              const interactive = Boolean(onRowClick);
              return (
                <tr
                  key={rowId}
                  className={`transition-colors duration-150 ease-out hover:bg-surface-raised ${
                    interactive ? 'cursor-pointer' : ''
                  }`}
                  tabIndex={interactive ? 0 : undefined}
                  role={interactive ? 'button' : undefined}
                  onClick={interactive ? () => onRowClick(row) : undefined}
                  onKeyDown={
                    interactive
                      ? (e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            onRowClick(row);
                          }
                        }
                      : undefined
                  }
                >
                  {columns.map((col) => {
                    const align = col.align === 'right' ? 'text-right' : 'text-left';
                    const tabular = col.tabular ? 'tabular-data text-foreground' : '';
                    const content =
                      col.cell?.(row) ??
                      (col.accessor ? col.accessor(row) : row[col.id]);
                    return (
                      <td
                        key={col.id}
                        className={`px-3 py-2 align-middle ${align} ${tabular} ${col.className ?? ''}`}
                      >
                        {content}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
