import React from 'react';
import logoLight from '../assets/branding/logo-light.png';
import logoDark from '../assets/branding/logo-dark.png';
import markLight from '../assets/branding/mark-light.png';
import markDark from '../assets/branding/mark-dark.png';

/**
 * Theme-aware MindQ brand mark / wordmark.
 *
 * Renders light and dark PNG variants; Tailwind `dark:` toggles visibility.
 * Use `collapsed` for the icon-only mark in tight layouts.
 *
 * `className` is applied to the wrapper so layout utilities like `mx-auto` /
 * `mb-6` position the brand correctly. Height/width on the wrapper drive
 * the visible image size via `h-full` on the imgs.
 *
 * @param {object} props
 * @param {boolean} [props.collapsed=false] When true, show mark; otherwise full logo.
 * @param {string} [props.className='h-8 w-auto'] Size and layout classes on the wrapper.
 * @param {string} [props.alt='MindQ'] Accessible name on the wrapper.
 */
export default function BrandLogo({
  collapsed = false,
  className = 'h-8 w-auto',
  alt = 'MindQ',
}) {
  const lightSrc = collapsed ? markLight : logoLight;
  const darkSrc = collapsed ? markDark : logoDark;

  return (
    <span
      className={`flex w-fit max-w-full items-center justify-center ${className}`}
      role="img"
      aria-label={alt}
    >
      <img
        src={lightSrc}
        alt=""
        className="h-full w-auto max-w-full block dark:hidden object-contain"
        draggable={false}
      />
      <img
        src={darkSrc}
        alt=""
        className="h-full w-auto max-w-full hidden dark:block object-contain"
        draggable={false}
      />
    </span>
  );
}
