import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api-client', () => ({
    default: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

vi.mock('../project.service', () => ({ ProjectService: {} }));

import apiClient from '../api-client';
import dataService from '../data.service';

describe('DataService.getBatchTimeline', () => {
    beforeEach(() => vi.clearAllMocks());

    it('GETs /data/batches/<id>/timeline/ with max_events param', async () => {
        apiClient.get.mockResolvedValue({
            data: { batch_id: 'B1', event_count: 3, events: [] },
        });
        await dataService.getBatchTimeline('B1', 150);
        const [url, opts] = apiClient.get.mock.calls[0];
        expect(url).toContain('/data/batches/B1/timeline/');
        expect(opts.params).toEqual({ max_events: 150 });
    });

    it('defaults max_events to 200', async () => {
        apiClient.get.mockResolvedValue({ data: { events: [] } });
        await dataService.getBatchTimeline('B1');
        expect(apiClient.get.mock.calls[0][1].params).toEqual({ max_events: 200 });
    });

    it('returns a safe empty shape on error', async () => {
        apiClient.get.mockRejectedValue(new Error('boom'));
        const result = await dataService.getBatchTimeline('B1');
        expect(result).toEqual({ batch_id: 'B1', event_count: 0, events: [] });
    });
});
