import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

// Import translation resources
import en from './locales/en.json';
import fr from './locales/fr.json';

const resources = {
    en: { translation: en },
    fr: { translation: fr }
};

// The page's lang attribute follows the language shown (screen readers,
// hyphenation, translation tools): at start and on every switch.
export const setPageLang = (lng) => {
    if (typeof document === 'undefined') return;
    const code = String(i18n.resolvedLanguage || lng || 'en').split('-')[0];
    document.documentElement.setAttribute('lang', code);
};
i18n.on('languageChanged', setPageLang);

i18n
    .use(LanguageDetector)
    .use(initReactI18next)
    .init({
        resources,
        fallbackLng: 'en',
        debug: false,

        interpolation: {
            escapeValue: false // React already escapes values
        },

        detection: {
            // Check localStorage first for user preference
            order: ['localStorage', 'navigator'],
            lookupLocalStorage: 'seropsLanguage',
            caches: ['localStorage']
        }
    });

export default i18n;
