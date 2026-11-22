import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key) => key }),
}));

const svc = { getBatchDetails: vi.fn() };
vi.mock('../../services/data.service', () => ({ default: svc }));

const { default: BatchTraces } = await import('../BatchTraces');

const span = (trace_id, extra = {}) => ({
  trace_id, service_name: 'checkout', operation_name: 'POST /pay', duration_ms: 1200, ...extra,
});

const renderWith = async (top_slow) => {
  svc.getBatchDetails.mockResolvedValue({
    batch_id: 'shop-1',
    data: { traces: { trace_count: 3, span_count: 9, error_span_count: 0, top_slow, top_errors: [] } },
  });
  render(
    <MemoryRouter initialEntries={['/dash/traces/batch/shop-1']}>
      <Routes><Route path="/dash/traces/batch/:batchId" element={<BatchTraces />} /></Routes>
    </MemoryRouter>,
  );
  await screen.findByText('aaaaaaaaaaaa…');
};

describe('BatchTraces trace ids', () => {
  it('links a trace id when the payload does not say, or says it was stored', async () => {
    await renderWith([
      span('aaaaaaaaaaaa1111'),
      span('bbbbbbbbbbbb2222', { trace_stored: true }),
    ]);
    expect(screen.getByRole('link', { name: 'aaaaaaaaaaaa…' })).toHaveAttribute('href', '/dash/traces/aaaaaaaaaaaa1111');
    expect(screen.getByRole('link', { name: 'bbbbbbbbbbbb…' })).toHaveAttribute('href', '/dash/traces/bbbbbbbbbbbb2222');
  });

  it('names its columns from the translations, and keeps red for a real error message', async () => {
    svc.getBatchDetails.mockResolvedValue({
      batch_id: 'shop-1',
      data: { traces: { trace_count: 3, span_count: 9, error_span_count: 2, top_slow: [], top_errors: [
        span('aaaaaaaaaaaa1111', { status_message: 'boom' }), span('dddddddddddd4444'),
      ] } },
    });
    render(
      <MemoryRouter initialEntries={['/dash/traces/batch/shop-1']}>
        <Routes><Route path="/dash/traces/batch/:batchId" element={<BatchTraces />} /></Routes>
      </MemoryRouter>,
    );
    await screen.findByText('aaaaaaaaaaaa…');
    const headers = screen.getAllByRole('columnheader').map((h) => h.textContent);
    expect(headers).toEqual(expect.arrayContaining(['traces.dashboard.operation', 'traces.dashboard.duration', 'detail.colMessage']));
    expect(headers).not.toContain('Operation');
    expect(screen.getByText('boom').className).toContain('text-danger');
    const empty = screen.getByText('dddddddddddd…').closest('tr').querySelectorAll('td')[2];
    expect(empty.textContent).toBe('—');
    expect(empty.className).not.toContain('text-danger');
  });

  it('shows a trace that was not stored as plain text', async () => {
    await renderWith([
      span('aaaaaaaaaaaa1111'),
      span('cccccccccccc3333', { trace_stored: false }),
    ]);
    expect(screen.getByText('cccccccccccc…')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'cccccccccccc…' })).toBeNull();
    expect(document.querySelector('a[href*="cccccccccccc3333"]')).toBeNull();
  });
});
