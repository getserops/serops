import './i18n';
import AuditStreamSettings from './AuditStreamSettings';

export default {
    settingsPages: [
        {
            path: 'audit-streaming', perm: 'team.manage', after: '/dash/settings/audit',
            label: (t) => t('ee.auditStream.menuLabel'), Component: AuditStreamSettings,
        },
    ],
};
