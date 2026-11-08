import { describe, expect, it } from 'vitest';
import { reportDownloadToast } from './report-download-toast';

describe('reportDownloadToast', () => {
  it('confirms a complete PDF', () => {
    expect(reportDownloadToast({ isHtml: false, synthesisStatus: 'ok' })).toMatchObject({
      title: 'Report ready',
      variant: 'success',
    });
  });

  it('warns that the narrative is still generating, even for an HTML fallback', () => {
    const toast = reportDownloadToast({ isHtml: true, synthesisStatus: 'generating' });
    expect(toast.variant).toBe('warning');
    expect(toast.description).toMatch(/still being generated/);
  });

  it('flags an HTML fallback when WeasyPrint is unavailable', () => {
    expect(reportDownloadToast({ isHtml: true, synthesisStatus: 'ok' })).toMatchObject({
      title: 'Report downloaded as HTML',
      variant: 'warning',
    });
  });

  it.each(['failed', 'skipped', ''])('treats %j narrative status as a finished download', (status) => {
    expect(reportDownloadToast({ isHtml: false, synthesisStatus: status }).variant).toBe('success');
  });
});
