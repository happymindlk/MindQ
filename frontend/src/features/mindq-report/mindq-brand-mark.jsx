import React from 'react';
// `?inline` embeds the latest MindQ wordmark as a data URL: SVG foreignObject
// rasterization (PDF export) refuses external images, so a plain asset URL
// would render blank there, while a data URL survives like the inlined
// client logo in render-report-pdf.js.
import logoLightInline from '../../assets/branding/logo-light.png?inline';

/**
 * MindQ brand wordmark using the latest brand asset in
 * `assets/branding/logo-light.png` (light variant: report surfaces are white).
 *
 * @param {{ size?: number }} props Height in px; width follows the wordmark aspect.
 */
export default function MindQBrandMark({ size = 22 }) {
  return (
    <span className="mq-brand" aria-label="MindQ">
      <img src={logoLightInline} alt="" style={{ height: size, width: 'auto', display: 'block' }} />
    </span>
  );
}
