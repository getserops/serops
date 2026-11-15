/**
 * Settings → Security → Single sign-on → SAML 2.0 (Enterprise, feature saml).
 *
 * What to register at the identity provider (our entity ID, ACS URL and
 * metadata), the identity provider's metadata, attribute names and the
 * security options. Roles and teams from groups are the shared SSO rules
 * below this panel (SSORoleMapping), the same as for OpenID Connect.
 *
 * Saved with the page: SecuritySettings calls the function given to
 * registerSave before it saves the SSO settings.
 */
import React, { useEffect, useRef, useState } from 'react';
import { Spinner } from 'react-bootstrap';
import { useTranslation } from 'react-i18next';
import apiClient from '../../services/api-client';

const ReadOnly = ({ id, label, value }) => (
    <div className="form-group mb-3">
        <label htmlFor={id}>{label}</label>
        <input id={id} type="text" className="form-control" value={value || ''} readOnly onFocus={(e) => e.target.select()} />
    </div>
);

const Toggle = ({ id, label, hint, checked, onChange }) => (
    <label className="toggle-item" htmlFor={id}>
        <div className="toggle-label">
            <span>{label}</span>
            <small>{hint}</small>
        </div>
        <input id={id} type="checkbox" role="switch" checked={!!checked} onChange={(e) => onChange(e.target.checked)} />
        <span className="toggle-slider"></span>
    </label>
);

const FIELDS = ['idp_metadata_url', 'email_attribute', 'first_name_attribute', 'last_name_attribute',
    'want_assertions_encrypted', 'allow_idp_initiated'];

const SamlSettings = ({ registerSave }) => {
    const { t } = useTranslation();
    const [config, setConfig] = useState(null);
    const [form, setForm] = useState({});
    const [error, setError] = useState(null);
    const state = useRef({ config: null, form: {} });
    state.current = { config, form };

    const load = () => apiClient.get('/ee/saml/config/')
        .then((res) => {
            setConfig(res.data);
            setForm(Object.fromEntries(FIELDS.map((f) => [f, res.data[f]])));
            setError(null);
        })
        .catch(() => setError(t('ee.saml.loadFailed')));

    useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        registerSave?.(async () => {
            const { config: saved, form: current } = state.current;
            if (!saved) return;
            const payload = {};
            FIELDS.forEach((f) => {
                if ((current[f] ?? '') !== (saved[f] ?? '')) payload[f] = current[f];
            });
            if (current.idp_metadata_xml?.trim()) payload.idp_metadata_xml = current.idp_metadata_xml;
            if (current.refresh_metadata) payload.refresh_metadata = true;
            if (!Object.keys(payload).length) return;
            const res = await apiClient.put('/ee/saml/config/', payload);
            setConfig(res.data);
            setForm(Object.fromEntries(FIELDS.map((f) => [f, res.data[f]])));
        });
        return () => registerSave?.(null);
    }, [registerSave]);

    if (error) return <div className="settings-subsection"><p className="form-hint">{error}</p></div>;
    if (!config) return <div className="settings-subsection"><Spinner animation="border" size="sm" /></div>;

    const set = (patch) => setForm((prev) => ({ ...prev, ...patch }));

    return (
        <>
            <div className="settings-subsection">
                <h3 className="settings-subsection-title">{t('ee.saml.registerTitle')}</h3>
                <p className="form-hint">{t('ee.saml.registerDesc')}</p>
                <ReadOnly id="saml-entity-id" label={t('ee.saml.entityId')} value={config.sp_entity_id} />
                <ReadOnly id="saml-acs-url" label={t('ee.saml.acsUrl')} value={config.acs_url} />
                <p className="form-hint">
                    {t('ee.saml.metadataUrl')}:{' '}
                    <a href={config.metadata_url} target="_blank" rel="noopener noreferrer" download>
                        {t('ee.saml.downloadMetadata')}
                    </a>
                </p>
            </div>

            <div className="settings-subsection">
                <h3 className="settings-subsection-title">{t('ee.saml.idpTitle')}</h3>
                <p className="form-hint">{t('ee.saml.idpDesc')}</p>
                <div className="form-group mb-3">
                    <label htmlFor="saml-idp-metadata-url">{t('ee.saml.idpMetadataUrl')}</label>
                    <input
                        id="saml-idp-metadata-url"
                        type="url"
                        className="form-control"
                        value={form.idp_metadata_url || ''}
                        onChange={(e) => set({ idp_metadata_url: e.target.value })}
                        placeholder="https://login.microsoftonline.com/<tenant>/federationmetadata/2007-06/federationmetadata.xml?appid=<app>"
                    />
                </div>
                <details className="mb-3">
                    <summary>{t('ee.saml.idpMetadataXml')}</summary>
                    <textarea
                        id="saml-idp-metadata-xml"
                        aria-label={t('ee.saml.idpMetadataXml')}
                        className="form-control mt-2"
                        rows={5}
                        value={form.idp_metadata_xml || ''}
                        onChange={(e) => set({ idp_metadata_xml: e.target.value })}
                        placeholder={'<md:EntityDescriptor ...'}
                    />
                </details>
                {config.idp_metadata_url && (
                    <Toggle
                        id="saml-refresh"
                        label={t('ee.saml.refresh')}
                        hint={t('ee.saml.refreshHint')}
                        checked={form.refresh_metadata}
                        onChange={(v) => set({ refresh_metadata: v })}
                    />
                )}
                {config.configured ? (
                    <dl className="saml-idp-summary">
                        <dt>{t('ee.saml.idpEntityId')}</dt>
                        <dd><code>{config.idp_entity_id}</code></dd>
                        <dt>{t('ee.saml.idpSsoUrl')}</dt>
                        <dd><code>{config.idp_sso_url}</code></dd>
                        <dt>{t('ee.saml.certificates')}</dt>
                        <dd>
                            <ul className="list-unstyled mb-0">
                                {config.idp_certificates.map((c) => (
                                    <li key={c.sha256 || c.subject}>
                                        {c.subject}
                                        {c.expires && <> · {t('ee.saml.expires', { date: c.expires.slice(0, 10) })}</>}
                                        {c.sha256 && <div className="text-muted small"><code>SHA-256 {c.sha256}</code></div>}
                                    </li>
                                ))}
                            </ul>
                        </dd>
                    </dl>
                ) : (
                    <p className="form-hint">{t('ee.saml.notConfigured')}</p>
                )}
            </div>

            <div className="settings-subsection">
                <h3 className="settings-subsection-title">{t('ee.saml.attributesTitle')}</h3>
                <p className="form-hint">{t('ee.saml.attributesDesc')}</p>
                <div className="row">
                    {[['email_attribute', 'emailAttribute'], ['first_name_attribute', 'firstNameAttribute'],
                        ['last_name_attribute', 'lastNameAttribute']].map(([field, label]) => (
                        <div className="col-md-4" key={field}>
                            <div className="form-group mb-3">
                                <label htmlFor={`saml-${field}`}>{t(`ee.saml.${label}`)}</label>
                                <input
                                    id={`saml-${field}`}
                                    type="text"
                                    className="form-control"
                                    value={form[field] || ''}
                                    onChange={(e) => set({ [field]: e.target.value })}
                                />
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            <div className="settings-subsection">
                <h3 className="settings-subsection-title">{t('ee.saml.optionsTitle')}</h3>
                <Toggle
                    id="saml-idp-initiated"
                    label={t('ee.saml.idpInitiated')}
                    hint={t('ee.saml.idpInitiatedHint')}
                    checked={form.allow_idp_initiated}
                    onChange={(v) => set({ allow_idp_initiated: v })}
                />
                <Toggle
                    id="saml-encrypted"
                    label={t('ee.saml.encrypted')}
                    hint={t('ee.saml.encryptedHint')}
                    checked={form.want_assertions_encrypted}
                    onChange={(v) => set({ want_assertions_encrypted: v })}
                />
                <details className="mb-3">
                    <summary>{t('ee.saml.spCertificate')}</summary>
                    <textarea
                        aria-label={t('ee.saml.spCertificate')}
                        className="form-control mt-2"
                        rows={5}
                        value={config.sp_certificate}
                        readOnly
                    />
                </details>
                <p className="form-hint">{t('ee.saml.signedNote', { skew: config.clock_skew_seconds })}</p>
            </div>
        </>
    );
};

export default SamlSettings;
