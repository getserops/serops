import { describe, it, expect } from 'vitest';
import { liveTested, liveTestedDetail, liveTestedText } from '../integrationMaturity';

describe('integrationMaturity', () => {
    it('names platform, version and date for the three cloud adapters', () => {
        expect(liveTestedText('cloudwatch')).toBe('Live-tested: EKS 1.36, SerOps 1.3.0, 2026-11-13');
        expect(liveTestedDetail('cloudwatch')).toBe('EKS 1.36, SerOps 1.3.0, 2026-11-13');
        expect(liveTested('gcp')).toEqual({ platform: 'GKE 1.36', version: '1.3.0', date: '2026-11-12' });
        expect(liveTested('azure').platform).toBe('AKS 1.36');
    });

    it('says nothing for other providers', () => {
        expect(liveTested('loki')).toBeNull();
        expect(liveTestedText('loki')).toBe('');
        expect(liveTestedDetail('loki')).toBe('');
        expect(liveTestedText(undefined)).toBe('');
    });
});
