import './i18n';
import LicenseSettings from './LicenseSettings';

export default {
    settingsPages: [
        { path: 'license', perm: 'license.manage', label: (t) => t('ee.license.menuLabel'), Component: LicenseSettings },
    ],
};
