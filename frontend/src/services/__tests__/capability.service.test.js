import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api-client', () => ({
    default: { get: vi.fn() },
}));

import apiClient from '../api-client';
import CapabilityService from '../capability.service';

describe('CapabilityService', () => {
    beforeEach(() => vi.clearAllMocks());

    it('GETs /organisation/capabilities/', async () => {
        apiClient.get.mockResolvedValue({
            data: { capabilities: ['logs', 'traces'], all_known: ['logs', 'metrics', 'code', 'cicd', 'traces'] },
        });
        const data = await CapabilityService.get();
        expect(apiClient.get).toHaveBeenCalledWith('/organisation/capabilities/');
        expect(data.capabilities).toEqual(['logs', 'traces']);
    });

    it('propagates errors', async () => {
        apiClient.get.mockRejectedValue(new Error('nope'));
        await expect(CapabilityService.get()).rejects.toThrow('nope');
    });
});
