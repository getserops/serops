import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('axios', () => ({
    default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

import axios from 'axios';
import { ProjectService } from '../project.service';

// The binding viewsets are mounted under /api/projects/ (Projects/urls.py).
// These calls used to omit /projects, so adding a CI/CD pipeline to a
// service failed with a 404, as did SCM webhook setup and sync.
describe('ProjectService binding URLs', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        for (const m of ['get', 'post', 'patch', 'put', 'delete']) axios[m].mockResolvedValue({ data: {} });
    });

    it('adds and deletes CI/CD bindings under /projects/cicd-bindings/', async () => {
        await ProjectService.addCICDBinding(7, { integration_id: 3, binding_type: 'deploy', pipeline_id: 'payments-deploy' });
        expect(axios.post.mock.calls[0][0]).toMatch(/\/projects\/cicd-bindings\/$/);
        await ProjectService.deleteCICDBinding(11);
        expect(axios.delete.mock.calls[0][0]).toMatch(/\/projects\/cicd-bindings\/11\/$/);
    });

    it('syncs and sets up SCM webhooks under /projects/scm-bindings/', async () => {
        await ProjectService.SyncSCMBinding(5);
        await ProjectService.SetupSCMWebhook(5);
        const urls = axios.post.mock.calls.map((c) => c[0]);
        expect(urls[0]).toMatch(/\/projects\/scm-bindings\/5\/sync\/$/);
        expect(urls[1]).toMatch(/\/projects\/scm-bindings\/5\/setup-webhook\/$/);
    });
});
