/**
 * Settings → Security → Provisioning (SCIM) (Enterprise, feature scim).
 *
 * The SCIM base URL to give the identity provider, and its tokens: create
 * (the value is shown once, never stored), list, revoke. Tokens are saved
 * at once, not with the page. Roles and teams come from the SSO group
 * rules on the same page.
 */
import React, { useEffect, useState } from 'react';
import { Badge, Button, Spinner, Table } from 'react-bootstrap';
import { useTranslation } from 'react-i18next';
import { toast } from 'react-toastify';
import apiClient from '../../services/api-client';

const URL = '/ee/scim/tokens/';
const day = (iso) => (iso ? iso.slice(0, 10) : null);

const ScimSettings = () => {
    const { t } = useTranslation();
    const [data, setData] = useState(null);
    const [error, setError] = useState(null);
    const [name, setName] = useState('');
    const [creating, setCreating] = useState(false);
    const [created, setCreated] = useState(null);

    const load = () => apiClient.get(URL)
        .then((res) => { setData(res.data); setError(null); })
        .catch(() => setError(t('ee.scim.loadFailed')));

    useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

    const create = async () => {
        setCreating(true);
        try {
            const res = await apiClient.post(URL, { name: name.trim() });
            setCreated(res.data);
            setName('');
            await load();
        } catch (err) {
            toast.error(err?.response?.data?.error || t('ee.scim.createFailed'));
        } finally {
            setCreating(false);
        }
    };

    const revoke = async (token) => {
        if (!window.confirm(t('ee.scim.revokeConfirm', { name: token.name }))) return;
        try {
            await apiClient.delete(`${URL}${token.id}/`);
            if (created?.id === token.id) setCreated(null);
            await load();
        } catch (err) {
            toast.error(err?.response?.data?.error || t('ee.scim.revokeFailed'));
        }
    };

    if (error) return <div className="settings-subsection"><p className="form-hint">{error}</p></div>;
    if (!data) return <div className="settings-subsection"><Spinner animation="border" size="sm" /></div>;

    return (
        <>
            <div className="settings-subsection">
                <h3 className="settings-subsection-title">{t('ee.scim.connectTitle')}</h3>
                <p className="form-hint">{t('ee.scim.connectDesc')}</p>
                <div className="form-group mb-3">
                    <label htmlFor="scim-base-url">{t('ee.scim.baseUrl')}</label>
                    <input id="scim-base-url" type="text" className="form-control" value={data.base_url} readOnly
                        onFocus={(e) => e.target.select()} />
                </div>
            </div>

            <div className="settings-subsection">
                <h3 className="settings-subsection-title">{t('ee.scim.tokensTitle')}</h3>
                <p className="form-hint">{t('ee.scim.tokensDesc')}</p>
                <div className="d-flex gap-2 align-items-end mb-3 flex-wrap">
                    <div className="form-group flex-grow-1">
                        <label htmlFor="scim-token-name">{t('ee.scim.tokenName')}</label>
                        <input id="scim-token-name" type="text" className="form-control" maxLength={100} value={name}
                            placeholder={t('ee.scim.tokenNamePlaceholder')} onChange={(e) => setName(e.target.value)} />
                    </div>
                    <Button variant="primary" onClick={create} disabled={creating || !name.trim()}>
                        {creating ? t('ee.scim.creating') : t('ee.scim.create')}
                    </Button>
                </div>
                {created && (
                    <div className="form-group mb-3" role="status">
                        <label htmlFor="scim-new-token">{t('ee.scim.newToken')}</label>
                        <input id="scim-new-token" type="text" className="form-control" value={created.token} readOnly
                            onFocus={(e) => e.target.select()} />
                    </div>
                )}
                {data.tokens.length === 0 ? (
                    <p className="form-hint">{t('ee.scim.noTokens')}</p>
                ) : (
                    <Table hover responsive size="sm" className="table-stack settings-table scim-tokens-table">
                        <thead>
                            <tr>
                                <th>{t('ee.scim.tokenName')}</th>
                                <th>{t('ee.scim.prefix')}</th>
                                <th>{t('ee.scim.createdAt')}</th>
                                <th>{t('ee.scim.lastUsed')}</th>
                                <th>{t('ee.scim.status')}</th>
                                <th aria-label={t('ee.scim.revoke')} />
                            </tr>
                        </thead>
                        <tbody>
                            {data.tokens.map((tok) => (
                                <tr key={tok.id} className={tok.revoked_at ? 'text-muted' : ''}>
                                    <td>
                                        <strong>{tok.name}</strong>
                                        {tok.created_by && <div className="small text-muted">{tok.created_by}</div>}
                                    </td>
                                    <td><code>{tok.prefix}…</code></td>
                                    <td>{day(tok.created_at)}</td>
                                    <td>{day(tok.last_used_at) || t('ee.scim.never')}</td>
                                    <td>
                                        {tok.revoked_at
                                            ? <Badge bg="secondary">{t('ee.scim.revoked')}</Badge>
                                            : <Badge bg="success">{t('ee.scim.active')}</Badge>}
                                    </td>
                                    <td>
                                        {!tok.revoked_at && (
                                            <Button variant="outline-danger" size="sm" onClick={() => revoke(tok)}>
                                                {t('ee.scim.revoke')}
                                            </Button>
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </Table>
                )}
                <p className="form-hint">{t('ee.scim.rulesNote')}</p>
            </div>
        </>
    );
};

export default ScimSettings;
