import { describe, it, expect, vi, beforeEach } from 'vitest';

// axios is also called as a function (AddGitLabProjectAsService).
vi.mock('axios', () => ({
    default: Object.assign(vi.fn(), { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() }),
}));
vi.mock('i18next', () => ({ default: { isInitialized: true, t: (key) => key } }));

import axios from 'axios';
import { ProjectService } from '../project.service';

const refused = (status, data) => Object.assign(new Error(`Request failed with status code ${status}`), { response: { status, data } });
const DEMO = refused(403, { error: 'demo_read_only', message: "You're in the SerOps live demo — sign up to make changes." });

// A refused create used to come back as {error}; the Projects page only
// catches, so it showed "Project created successfully!" for a project the
// server had refused (seen on the live demo, 21 Nov 2026).
describe('ProjectService: a refused write is never a success', () => {
    beforeEach(() => vi.clearAllMocks());

    it('CreateProject rejects when the server refuses, like UpdateProject and DeleteProject', async () => {
        axios.post.mockRejectedValue(DEMO);
        await expect(ProjectService.CreateProject({ name: 'x' })).rejects.toBe(DEMO);
        const duplicate = refused(400, { error: 'A project with this name already exists' });
        axios.post.mockRejectedValue(duplicate);
        await expect(ProjectService.CreateProject({ name: 'x' })).rejects.toBe(duplicate);
        axios.put.mockRejectedValue(DEMO);
        await expect(ProjectService.UpdateProject(1, { name: 'x' })).rejects.toBe(DEMO);
        axios.delete.mockRejectedValue(DEMO);
        await expect(ProjectService.DeleteProject(1)).rejects.toBe(DEMO);
    });

    it('CreateProject still returns the project when the server accepts', async () => {
        axios.post.mockResolvedValue({ data: { id: 4, name: 'x' } });
        await expect(ProjectService.CreateProject({ name: 'x' })).resolves.toEqual({ id: 4, name: 'x' });
    });

    const ADDERS = [
        ['AddCustomService', (s) => s.AddCustomService(1, { name: 'x' })],
        ['AddApplicationService', (s) => s.AddApplicationService(1, { name: 'x' })],
        ['AddInfraService', (s) => s.AddInfraService(1, { name: 'x' })],
        ['AddGitHubProjectAsService', (s) => s.AddGitHubProjectAsService(1, { name: 'x' })],
        ['AddBitbucketProjectAsService', (s) => s.AddBitbucketProjectAsService(1, { name: 'x' })],
        ['AddGitLabProjectAsService', (s) => s.AddGitLabProjectAsService(1, { name: 'x' })],
    ];

    it.each(ADDERS)('%s returns the read-only sentence on the demo, not the code', async (_name, call) => {
        axios.mockRejectedValue(DEMO);
        axios.post.mockRejectedValue(DEMO);
        const result = await call(ProjectService);
        expect(result.error).toBe('demo.readOnlyNotice');
    });

    it.each(ADDERS)('%s still returns what the server said for any other refusal', async (_name, call) => {
        const taken = refused(400, { error: 'A service with this name already exists' });
        axios.mockRejectedValue(taken);
        axios.post.mockRejectedValue(taken);
        const result = await call(ProjectService);
        expect(result.error).toContain('A service with this name already exists');
    });
});
