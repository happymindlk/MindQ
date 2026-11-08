/**
 * Toast copy for a server-rendered report download.
 *
 * @param {{ isHtml: boolean, synthesisStatus: string }} result From `adminApi.downloadReport`.
 * @returns {{ title: string, description: string, variant: 'success' | 'warning' }}
 */
export function reportDownloadToast({ isHtml, synthesisStatus }) {
  if (synthesisStatus === 'generating') {
    return {
      title: 'Report downloaded',
      description:
        'The executive summary is still being generated. Download again in a minute for the full report.',
      variant: 'warning',
    };
  }
  if (isHtml) {
    return {
      title: 'Report downloaded as HTML',
      description: 'PDF rendering is unavailable on the server right now.',
      variant: 'warning',
    };
  }
  return {
    title: 'Report ready',
    description: 'Assessment report PDF downloaded.',
    variant: 'success',
  };
}
