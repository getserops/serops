import '@testing-library/jest-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k, o) => (o && o.error ? `${k}:${o.error}` : k) }) }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock('react-toastify', () => ({ toast }));
const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() }));
vi.mock('../../../services/api-client', () => ({ default: api }));
vi.mock('../../../utils/permissions', () => ({ usePermissions: () => () => true }));

import AuditStreamSettings, { payloadOf, stateOf } from '../AuditStreamSettings';
import fs from 'fs';
import path from 'path';
import { strings } from '../i18n';

const HTTP = {
    id: 1, name: 'Splunk', kind: 'http', enabled: true, target: 'https://splunk.example/services/collector/event',
    url: 'https://splunk.example/services/collector/event', http_format: 'splunk_hec', auth_header_name: 'Authorization',
    auth_header_configured: true, signing_secret_configured: false, host: '', port: null, transport: 'tls', ca_certificate: '',
    last_success_at: '2026-11-14T10:00:00+00:00', last_failure_at: null, last_error: '', delivered_count: 42, pending: 0,
};
const SYSLOG = {
    ...HTTP, id: 2, name: 'QRadar', kind: 'syslog', target: 'siem.example:6514', url: '', host: 'siem.example', port: 6514,
    last_success_at: '2026-11-14T09:00:00+00:00', last_failure_at: '2026-11-14T10:00:00+00:00',
    last_error: 'TLS certificate not trusted for siem.example', pending: 3,
};

const renderPage = async (data) => {
    api.get.mockResolvedValue({ data });
    render(<MemoryRouter><AuditStreamSettings /></MemoryRouter>);
    await screen.findByText('ee.auditStream.title');
};

describe('Audit streaming settings (Enterprise)', () => {
    beforeEach(() => {
        Object.values(api).forEach((fn) => fn.mockReset());
        Object.values(toast).forEach((fn) => fn.mockReset());
    });

    it('lists destinations with their delivery state', async () => {
        await renderPage({ licensed: true, destinations: [HTTP, SYSLOG] });
        const rows = screen.getAllByRole('row');
        expect(within(rows[1]).getByText('ee.auditStream.healthy')).toBeInTheDocument();
        expect(within(rows[2]).getByText('ee.auditStream.failing')).toBeInTheDocument();
        expect(within(rows[2]).getByText(/TLS certificate not trusted/)).toBeInTheDocument();
        expect(screen.getByText('siem.example:6514')).toBeInTheDocument();
    });

    it('sends a test event and says what happened', async () => {
        await renderPage({ licensed: true, destinations: [HTTP] });
        api.post.mockResolvedValueOnce({ data: { ok: false, error: 'The destination answered HTTP 401' } });
        fireEvent.click(screen.getByRole('button', { name: 'ee.auditStream.test' }));
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith('ee.auditStream.testFailed:The destination answered HTTP 401'));
        expect(api.post).toHaveBeenCalledWith('/ee/audit-streams/1/test/');
    });

    it('adds a syslog destination', async () => {
        await renderPage({ licensed: true, destinations: [] });
        api.post.mockResolvedValue({ data: {} });
        fireEvent.click(screen.getByRole('button', { name: 'ee.auditStream.add' }));
        fireEvent.change(screen.getByLabelText('ee.auditStream.name'), { target: { value: 'SIEM' } });
        fireEvent.click(screen.getByRole('radio', { name: /ee.auditStream.kindSyslog/ }));
        fireEvent.change(screen.getByLabelText('ee.auditStream.host'), { target: { value: 'siem.example' } });
        fireEvent.click(screen.getByRole('button', { name: 'ee.auditStream.save' }));
        await waitFor(() => expect(api.post).toHaveBeenCalledWith('/ee/audit-streams/', {
            name: 'SIEM', enabled: true, kind: 'syslog', host: 'siem.example', port: 6514, transport: 'tls', ca_certificate: '',
        }));
    });

    it('without the license: explains, and offers only turning off and removing', async () => {
        await renderPage({ licensed: false, destinations: [HTTP] });
        expect(screen.getByText(/ee.auditStream.unlicensed/)).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'ee.auditStream.add' })).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'ee.auditStream.test' })).not.toBeInTheDocument();
        api.put.mockResolvedValue({ data: {} });
        fireEvent.click(screen.getByRole('button', { name: 'ee.auditStream.off' }));
        await waitFor(() => expect(api.put).toHaveBeenCalledWith('/ee/audit-streams/1/', { enabled: false }));
        expect(screen.getByRole('button', { name: 'ee.auditStream.remove' })).toBeInTheDocument();
    });

    it('shows a message, not a broken page, when the list cannot be read', async () => {
        api.get.mockRejectedValue(new Error('403'));
        render(<MemoryRouter><AuditStreamSettings /></MemoryRouter>);
        expect(await screen.findByText('ee.auditStream.loadFailed')).toBeInTheDocument();
    });
});

describe('payloadOf / stateOf', () => {
    it('sends secrets only when typed or cleared, and only the fields of the kind', () => {
        const form = { ...HTTP, auth_header_value: '', signing_secret: '' };
        expect(payloadOf(form, HTTP)).toEqual({
            name: 'Splunk', enabled: true, url: HTTP.url, http_format: 'splunk_hec', auth_header_name: 'Authorization',
            ca_certificate: '',
        });
        expect(payloadOf({ ...form, auth_header_value: 'Splunk new' }, HTTP).auth_header_value).toBe('Splunk new');
        expect(payloadOf({ ...form, clear_signing: true }, HTTP).signing_secret).toBe('');
        expect(payloadOf({ ...form, kind: 'http' }, null).kind).toBe('http');
    });

    it('names the state', () => {
        expect(stateOf({ enabled: false })).toBe('off');
        expect(stateOf({ enabled: true })).toBe('waiting');
        expect(stateOf(HTTP)).toBe('healthy');
        expect(stateOf(SYSLOG)).toBe('failing');
    });
});

describe('Audit streaming strings', () => {
    it('has every key the page uses, in English and French', () => {
        const src = fs.readFileSync(path.resolve(__dirname, '../AuditStreamSettings.jsx'), 'utf8');
        const used = [...src.matchAll(/'ee\.auditStream\.([a-zA-Z]+)'/g)].map((m) => m[1])
            .concat(['healthy', 'failing', 'waiting', 'off']);
        expect(used.length).toBeGreaterThan(30);
        for (const lng of ['en', 'fr']) {
            expect(used.filter((key) => !strings[lng][key])).toEqual([]);
        }
        expect(Object.keys(strings.fr).sort()).toEqual(Object.keys(strings.en).sort());
    });
});
