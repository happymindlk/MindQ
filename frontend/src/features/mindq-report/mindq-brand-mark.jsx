import React from 'react';

/**
 * MindQ brand mark rendered as inline SVG so it survives SVG foreignObject
 * rasterization (external <img> sources are blocked there).
 *
 * @param {{ size?: number }} props
 */
export default function MindQBrandMark({ size = 22 }) {
  return (
    <span className="mq-brand" aria-label="MindQ">
      <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
        <rect width="24" height="24" rx="6" fill="#4f46e5" />
        <circle cx="11.25" cy="11.25" r="5.25" fill="none" stroke="#ffffff" strokeWidth="2.2" />
        <path d="M14.6 14.6 L18.2 18.2" stroke="#ffffff" strokeWidth="2.4" strokeLinecap="round" />
      </svg>
      <span className="mq-brand-word">
        Mind<span className="mq-brand-q">Q</span>
      </span>
    </span>
  );
}
