import React from 'react';
import { Modal, Button, Alert, Table } from 'react-bootstrap';
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
    const getSeverityBadge = (severity) => {
        const colors = {
            critical: 'danger',
            high: 'warning',
            medium: 'info',
            low: 'secondary',
        };
        return (
            <span className={`badge bg-${colors[severity] || 'secondary'}`}>
                {severity}
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
            password: 'Password',
            api_key: 'API Key',
            aws_access_key: 'AWS Access Key',
            aws_secret_key: 'AWS Secret Key',
            jwt_token: 'JWT Token',
            bearer_token: 'Bearer Token',
            private_key: 'Private Key',
            ssh_key: 'SSH Key',
            gitlab_token: 'GitLab Token',
            github_token: 'GitHub Token',
            slack_token: 'Slack Token',
            generic_secret: 'Secret/Token',
            email: 'Email Address',
            phone_us: 'Phone Number',
            phone_international: 'Phone Number',
            ssn: 'Social Security Number',
            credit_card: 'Credit Card',
            credit_card_formatted: 'Credit Card',
            connection_string: 'Database Connection',
            database_url: 'Database URL',
            s3_bucket: 'S3 Bucket',
            private_ip: 'Internal IP',
            env_variable: 'Environment Variable',
        };
        return labels[type] || type;
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
                    Sensitive Data Detected!
                </Modal.Title>
            </Modal.Header>

            <Modal.Body>
                <Alert variant="warning" className="mb-3">
                    <strong>Your message contains potentially sensitive information.</strong>
                    <br />
                    <small>This data will be sent to an external AI service if you proceed.</small>
                </Alert>

                {(criticalCount > 0 || highCount > 0) && (
                    <div className="severity-summary mb-3">
                        {criticalCount > 0 && (
                            <span className="badge bg-danger me-2">
                                {criticalCount} Critical
                            </span>
                        )}
                        {highCount > 0 && (
                            <span className="badge bg-warning text-dark">
                                {highCount} High Risk
                            </span>
                        )}
                    </div>
                )}

                <h6 className="mt-3">Detected Sensitive Data:</h6>
                <div className="findings-table-container">
                    <Table size="sm" bordered hover className="findings-table">
                        <thead>
                            <tr>
                                <th>Type</th>
                                <th>Risk</th>
                                <th>Preview</th>
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
                        <strong>What happens if I send anyway?</strong><br />
                        The message will be sent to the AI service <u>without modifications</u>.
                        The AI may see passwords, tokens, or personal data.
                    </small>
                </Alert>
            </Modal.Body>

            <Modal.Footer className="d-flex justify-content-between">
                <Button variant="outline-secondary" onClick={onCancel}>
                    <FaTimes className="me-1" /> Cancel & Edit
                </Button>
                <Button variant="warning" onClick={onSendAnyway}>
                    <FaPaperPlane className="me-1" /> Send Anyway
                </Button>
            </Modal.Footer>
        </Modal>
    );
};

export default SensitiveDataWarningModal;
