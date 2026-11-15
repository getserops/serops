import './i18n';
import SamlSettings from './SamlSettings';

export default {
    securitySections: [
        { key: 'saml', feature: 'saml', Component: SamlSettings },
    ],
};
