import JSZip from 'jszip';
import { describe, expect, it, vi } from 'vitest';
import { buildReportsZip } from './build-reports-zip';
import { reportFilename } from './report-filename';

const renderPdf = vi.fn(async (data) => ({
  blob: new Blob([`pdf:${data.candidate_name}`], { type: 'application/pdf' }),
  filename: reportFilename(data.candidate_name),
}));

function fetchByName(names) {
  return vi.fn(async (id) => {
    const name = names[id];
    if (name instanceof Error) throw name;
    return { candidate_id: id, candidate_name: name };
  });
}

async function listEntries(blob) {
  const zip = await JSZip.loadAsync(await blob.arrayBuffer());
  return Object.keys(zip.files).sort();
}

describe('buildReportsZip', () => {
  it('bundles one PDF per candidate and dedupes identical names', async () => {
    const onProgress = vi.fn();
    const { blob, succeeded, failures } = await buildReportsZip({
      candidates: [
        { candidate_id: 'a', name: 'Jane Doe' },
        { candidate_id: 'b', name: 'Jane Doe' },
        { candidate_id: 'c', name: 'Raj Kumar' },
      ],
      fetchReportData: fetchByName({ a: 'Jane Doe', b: 'Jane Doe', c: 'Raj Kumar' }),
      onProgress,
      renderPdf,
    });

    expect(succeeded).toBe(3);
    expect(failures).toEqual([]);
    expect(await listEntries(blob)).toEqual([
      'MindQ Report - Jane Doe (2).pdf',
      'MindQ Report - Jane Doe.pdf',
      'MindQ Report - Raj Kumar.pdf',
    ]);
    expect(onProgress).toHaveBeenLastCalledWith({ done: 3, total: 3 });
  });

  it('skips failed candidates without aborting the batch', async () => {
    const { blob, succeeded, failures } = await buildReportsZip({
      candidates: [
        { candidate_id: 'a', name: 'Jane Doe' },
        { candidate_id: 'b', name: 'Broken Candidate' },
      ],
      fetchReportData: fetchByName({ a: 'Jane Doe', b: new Error('Candidate not found') }),
      renderPdf,
    });

    expect(succeeded).toBe(1);
    expect(failures).toEqual([{ name: 'Broken Candidate', message: 'Candidate not found' }]);
    expect(await listEntries(blob)).toEqual(['MindQ Report - Jane Doe.pdf']);
  });

  it('fails when every report fails', async () => {
    await expect(
      buildReportsZip({
        candidates: [{ candidate_id: 'a', name: 'A' }],
        fetchReportData: fetchByName({ a: new Error('Service unavailable') }),
        renderPdf,
      }),
    ).rejects.toThrow('Service unavailable');
  });

  it('rejects an empty roster', async () => {
    await expect(
      buildReportsZip({ candidates: [], fetchReportData: vi.fn(), renderPdf }),
    ).rejects.toThrow('No completed reports');
  });

  it('stops when cancelled', async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(
      buildReportsZip({
        candidates: [{ candidate_id: 'a', name: 'A' }],
        fetchReportData: fetchByName({ a: 'A' }),
        signal: controller.signal,
        renderPdf,
      }),
    ).rejects.toMatchObject({ name: 'AbortError' });
  });
});
