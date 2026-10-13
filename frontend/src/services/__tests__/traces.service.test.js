import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api-client', () => ({
    default: {
        get: vi.fn(),
        post: vi.fn(),
        delete: vi.fn(),
    },
}));

import apiClient from '../api-client';
import TracesService from '../traces.service';

describe('TracesService.IngestKeys', () => {
    beforeEach(() => vi.clearAllMocks());

    it('list GETs /traces/keys/', async () => {
        apiClient.get.mockResolvedValue({ data: [{ id: 1, name: 'k' }] });
        const result = await TracesService.IngestKeys.list();
        expect(apiClient.get).toHaveBeenCalledWith('/traces/keys/');
        expect(result).toEqual([{ id: 1, name: 'k' }]);
    });

    it('create POSTs name, returns plaintext', async () => {
        apiClient.post.mockResolvedValue({
            data: { id: 9, name: 'x', plaintext: 'serops_otlp_abc' },
        });
        const result = await TracesService.IngestKeys.create('x');
        expect(apiClient.post).toHaveBeenCalledWith('/traces/keys/', { name: 'x' });
        expect(result.plaintext).toBe('serops_otlp_abc');
    });

    it('revoke DELETEs by id', async () => {
        apiClient.delete.mockResolvedValue({});
        await TracesService.IngestKeys.revoke(42);
        expect(apiClient.delete).toHaveBeenCalledWith('/traces/keys/42/');
    });
});

describe('TracesService.Traces', () => {
    beforeEach(() => vi.clearAllMocks());

    it('list forwards non-empty filters as query params', async () => {
        apiClient.get.mockResolvedValue({ data: { count: 0, results: [] } });
        await TracesService.Traces.list({
            service: 'checkout',
            status: 'ERROR',
            min_duration_ms: '',      // omitted
            since: null,              // omitted
            page: 2,
        });
        expect(apiClient.get).toHaveBeenCalledWith(
            '/traces/traces/',
            { params: { service: 'checkout', status: 'ERROR', page: 2 } },
        );
    });

    it('list drops undefined/null/empty filter values', async () => {
        apiClient.get.mockResolvedValue({ data: { count: 0, results: [] } });
        await TracesService.Traces.list({ a: '', b: null, c: undefined });
        expect(apiClient.get).toHaveBeenCalledWith(
            '/traces/traces/',
            { params: {} },
        );
    });

    it('get requests /traces/traces/<id>/', async () => {
        apiClient.get.mockResolvedValue({ data: { trace_id: 'abc' } });
        const result = await TracesService.Traces.get('abc');
        expect(apiClient.get).toHaveBeenCalledWith('/traces/traces/abc/');
        expect(result).toEqual({ trace_id: 'abc' });
    });

    it('services returns array from backend', async () => {
        apiClient.get.mockResolvedValue({ data: ['api', 'checkout'] });
        const result = await TracesService.Traces.services();
        expect(apiClient.get).toHaveBeenCalledWith('/traces/traces/services/');
        expect(result).toEqual(['api', 'checkout']);
    });

    it('list propagates errors', async () => {
        apiClient.get.mockRejectedValue(new Error('boom'));
        await expect(TracesService.Traces.list()).rejects.toThrow('boom');
    });
});
