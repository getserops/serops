import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api-client', () => ({
    default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import apiClient from '../api-client';
import ClusterService from '../cluster.service';

describe('ClusterService.workloads', () => {
    beforeEach(() => vi.clearAllMocks());

    it('GETs /clusters/<id>/workloads/', async () => {
        apiClient.get.mockResolvedValue({
            data: { cluster: { id: 3, name: 'prod-eks' }, projects: [] },
        });
        const r = await ClusterService.workloads(3);
        expect(apiClient.get).toHaveBeenCalledWith('/integrations/clusters/3/workloads/');
        expect(r.cluster.id).toBe(3);
        expect(r.projects).toEqual([]);
    });

    it('propagates errors', async () => {
        apiClient.get.mockRejectedValue(new Error('boom'));
        await expect(ClusterService.workloads(3)).rejects.toThrow('boom');
    });
});
