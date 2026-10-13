import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api-client', () => ({
    default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import apiClient from '../api-client';
import ClusterService from '../cluster.service';

describe('ClusterService', () => {
    beforeEach(() => vi.clearAllMocks());

    it('list unwraps DRF paginated shape', async () => {
        apiClient.get.mockResolvedValue({ data: { results: [{ id: 1, name: 'c1' }] } });
        const rows = await ClusterService.list();
        expect(apiClient.get).toHaveBeenCalledWith('/integrations/clusters/');
        expect(rows).toEqual([{ id: 1, name: 'c1' }]);
    });

    it('list handles bare array response', async () => {
        apiClient.get.mockResolvedValue({ data: [{ id: 1 }] });
        const rows = await ClusterService.list();
        expect(rows).toEqual([{ id: 1 }]);
    });

    it('create POSTs payload', async () => {
        apiClient.post.mockResolvedValue({ data: { id: 9, name: 'prod-eks' } });
        const r = await ClusterService.create({ name: 'prod-eks', provider: 'eks' });
        expect(apiClient.post).toHaveBeenCalledWith(
            '/integrations/clusters/',
            { name: 'prod-eks', provider: 'eks' },
        );
        expect(r.id).toBe(9);
    });

    it('update PATCHes by id', async () => {
        apiClient.patch.mockResolvedValue({ data: {} });
        await ClusterService.update(3, { is_active: false });
        expect(apiClient.patch).toHaveBeenCalledWith(
            '/integrations/clusters/3/',
            { is_active: false },
        );
    });

    it('delete DELETEs by id', async () => {
        apiClient.delete.mockResolvedValue({});
        await ClusterService.delete(42);
        expect(apiClient.delete).toHaveBeenCalledWith('/integrations/clusters/42/');
    });

    it('propagates errors', async () => {
        apiClient.get.mockRejectedValue(new Error('boom'));
        await expect(ClusterService.list()).rejects.toThrow('boom');
    });
});
