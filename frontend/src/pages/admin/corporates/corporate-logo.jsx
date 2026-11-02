import React, { useEffect, useMemo, useState } from 'react';
import { cacheBustUrl } from '../../../lib/cache-bust-url';
import { companyInitials } from './corporate-initials';

const SIZES = {
  sm: 'h-8 w-8 text-[10px]',
  md: 'h-10 w-10 text-xs',
  lg: 'h-16 w-16 text-base',
};

/**
 * Square logo tile with an initials fallback when the image is missing or broken.
 *
 * @param {object} props
 * @param {string} props.name
 * @param {string | null | undefined} props.logoUrl
 * @param {'sm' | 'md' | 'lg'} [props.size='md']
 */
export default function CorporateLogo({ name, logoUrl, size = 'md' }) {
  const [failed, setFailed] = useState(false);
  const displayUrl = useMemo(() => (logoUrl ? cacheBustUrl(logoUrl) : ''), [logoUrl]);

  useEffect(() => {
    setFailed(false);
  }, [displayUrl]);

  const box = SIZES[size] ?? SIZES.md;

  if (displayUrl && !failed) {
    return (
      <img
        src={displayUrl}
        alt=""
        onError={() => setFailed(true)}
        className={`${box} shrink-0 rounded-md border border-slate-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 object-contain p-1`}
      />
    );
  }
  return (
    <div
      aria-hidden="true"
      className={`${box} shrink-0 rounded-md border border-slate-200 dark:border-neutral-800 bg-slate-100 dark:bg-neutral-900 flex items-center justify-center font-semibold tabular-data text-neutral-500 dark:text-neutral-400`}
    >
      {companyInitials(name)}
    </div>
  );
}
