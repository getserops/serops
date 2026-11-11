"""The Enterprise features a license key can enable.

Enterprise is for the governance needs of large organisations (central
identity, compliance, administration at scale). Anything that serves
security, reliability or the analysis itself belongs in Community; see
docs/src/open-source-promise.md.
"""

FEATURES = {
    'saml': 'SAML 2.0 single sign-on',
    'scim': 'SCIM user and group provisioning',
    'custom_roles': 'Custom roles',
    'project_access': 'Per-project access',
    'audit_streaming': 'Real-time audit streaming to a SIEM',
    'delegated_admin': 'Delegated administration across organisations',
    'compliance_reports': 'Compliance reports',
}
