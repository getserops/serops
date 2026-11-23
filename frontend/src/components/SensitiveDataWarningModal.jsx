import React from 'react';
import { Modal, Button, Alert, Table } from 'react-bootstrap';
import { useTranslation } from 'react-i18next';
import { FaExclamationTriangle, FaShieldAlt, FaPaperPlane, FaTimes } from 'react-icons/fa';
import './SensitiveDataWarningModal.css';

/**
 * Modal that warns users about sensitive data in their chat message.
 * 
 * Shows:
 * - List of detected sensitive data with severity
 * - Preview of where sensitive data was found (masked)
 * - Options to Cancel & Edit or Send Anyway
 * 
 * @param {boolean} show - Whether to show the modal
 * @param {Function} onHide - Called when modal is closed
 * @param {Function} onSendAnyway - Called when user chooses to send anyway
 * @param {Function} onCancel - Called when user chooses to cancel and edit
 * @param {Array} findings - Array of sensitive data findings
 */
const SensitiveDataWarningModal = ({
    show,
    onHide,
    onSendAnyway,
    onCancel,
    findings = []
}) => {
    const { t } = useTranslation();
    const getSeverityBadge = (severity) => {
        const colors = {
            critical: 'danger',
            high: 'warning',
            medium: 'info',
            low: 'secondary',
        };
        return (
            <span className={`badge bg-${colors[severity] || 'secondary'}`}>
                {t(`sensitiveDataWarningModal.severity.${severity}`, { defaultValue: severity })}
            </span>
        );
    };

    const getSeverityIcon = (severity) => {
        if (severity === 'critical') return '🔴';
        if (severity === 'high') return '🟠';
        if (severity === 'medium') return '🟡';
        return '⚪';
    };

    const getTypeLabel = (type) => {
        const labels = {
            password: 'sensitiveDataWarningModal.type.password',
            api_key: 'sensitiveDataWarningModal.type.apiKey',
            aws_access_key: 'sensitiveDataWarningModal.type.awsAccessKey',
            aws_secret_key: 'sensitiveDataWarningModal.type.awsSecretKey',
            jwt_token: 'sensitiveDataWarningModal.type.jwtToken',
            bearer_token: 'sensitiveDataWarningModal.type.bearerToken',
            private_key: 'sensitiveDataWarningModal.type.privateKey',
            ssh_key: 'sensitiveDataWarningModal.type.sshKey',
            gitlab_token: 'sensitiveDataWarningModal.type.gitlabToken',
            github_token: 'sensitiveDataWarningModal.type.githubToken',
            slack_token: 'sensitiveDataWarningModal.type.slackToken',
            ai_provider_key: 'sensitiveDataWarningModal.type.aiProviderKey',
            google_api_key: 'sensitiveDataWarningModal.type.googleApiKey',
            docker_login_password: 'sensitiveDataWarningModal.type.dockerLoginPassword',
            authorization_header: 'sensitiveDataWarningModal.type.authorizationHeader',
            basic_auth: 'sensitiveDataWarningModal.type.basicAuth',
            url_credentials: 'sensitiveDataWarningModal.type.urlCredentials',
            generic_secret: 'sensitiveDataWarningModal.type.genericSecret',
            email: 'sensitiveDataWarningModal.type.email',
            phone_us: 'sensitiveDataWarningModal.type.phoneUs',
            phone_international: 'sensitiveDataWarningModal.type.phoneInternational',
            ssn: 'sensitiveDataWarningModal.type.ssn',
            credit_card: 'sensitiveDataWarningModal.type.creditCard',
            credit_card_formatted: 'sensitiveDataWarningModal.type.creditCardFormatted',
            connection_string: 'sensitiveDataWarningModal.type.connectionString',
            database_url: 'sensitiveDataWarningModal.type.databaseUrl',
            s3_bucket: 'sensitiveDataWarningModal.type.s3Bucket',
            private_ip: 'sensitiveDataWarningModal.type.privateIp',
            public_ip: 'sensitiveDataWarningModal.type.publicIp',
            env_variable: 'sensitiveDataWarningModal.type.envVariable',
        };
        return labels[type] ? t(labels[type]) : type;
    };

    // Calculate severity summary
    const criticalCount = findings.filter(f => f.severity === 'critical').length;
    const highCount = findings.filter(f => f.severity === 'high').length;

    return (
        <Modal
            show={show}
            onHide={onHide}
            centered
            backdrop="static"
            className="sensitive-data-warning-modal"
        >
            <Modal.Header className="warning-header">
                <Modal.Title>
                    <FaExclamationTriangle className="me-2" />
                    {t('sensitiveDataWarningModal.title')}
                </Modal.Title>
            </Modal.Header>

            <Modal.Body>
                <Alert variant="warning" className="mb-3">
                    <strong>{t('sensitiveDataWarningModal.intro')}</strong>
                    <br />
                    <small>{t('sensitiveDataWarningModal.introHint')}</small>
                </Alert>

                {(criticalCount > 0 || highCount > 0) && (
                    <div className="severity-summary mb-3">
                        {criticalCount > 0 && (
                            <span className="badge bg-danger me-2">
                                {t('sensitiveDataWarningModal.criticalCount', { n: criticalCount })}
                            </span>
                        )}
                        {highCount > 0 && (
                            <span className="badge bg-warning text-dark">
                                {t('sensitiveDataWarningModal.highCount', { n: highCount })}
                            </span>
                        )}
                    </div>
                )}

                <h6 className="mt-3">{t('sensitiveDataWarningModal.detected')}</h6>
                <div className="findings-table-container">
                    <Table size="sm" bordered hover className="findings-table">
                        <thead>
                            <tr>
                                <th>{t('sensitiveDataWarningModal.col.type')}</th>
                                <th>{t('sensitiveDataWarningModal.col.risk')}</th>
                                <th>{t('sensitiveDataWarningModal.col.preview')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {findings.map((finding, idx) => (
                                <tr key={idx} className={`severity-${finding.severity}`}>
                                    <td>
                                        {getSeverityIcon(finding.severity)}{' '}
                                        {getTypeLabel(finding.type)}
                                    </td>
                                    <td>{getSeverityBadge(finding.severity)}</td>
                                    <td>
                                        <code className="preview-code">
                                            ...{finding.preview}...
                                        </code>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </Table>
                </div>

                <Alert variant="info" className="mt-3 mb-0 info-alert">
                    <small>
                        <FaShieldAlt className="me-1" />
                        <strong>{t('sensitiveDataWarningModal.whatIfTitle')}</strong><br />
                        {t('sensitiveDataWarningModal.whatIfBody')}
                    </small>
                </Alert>
            </Modal.Body>

            <Modal.Footer className="d-flex justify-content-between">
                <Button variant="outline-secondary" onClick={onCancel}>
                    <FaTimes className="me-1" /> {t('sensitiveDataWarningModal.cancelEdit')}
                </Button>
                <Button variant="warning" onClick={onSendAnyway}>
                    <FaPaperPlane className="me-1" /> {t('sensitiveDataWarningModal.sendAnyway')}
                </Button>
            </Modal.Footer>
        </Modal>
    );
};

export default SensitiveDataWarningModal;
