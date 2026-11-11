// The shared i18next instance (initialised in src/i18n.js); bundles are added
// once it is ready, whatever the import order.
import i18n from 'i18next';

export const strings = {
    en: {
        menuLabel: 'Enterprise license',
        title: 'Enterprise license',
        subtitle: 'SerOps Community is complete without a license. A license key adds the Enterprise governance features.',
        currentTitle: 'Current license',
        currentDesc: 'Covers every organisation on this install.',
        none: 'No license installed. Every Community feature works without one.',
        licensee: 'Licensee',
        status: 'Status',
        expires: 'Valid until',
        licenseId: 'License ID',
        features: 'Enterprise features',
        statusValid: 'Valid',
        statusExpired: 'Expired',
        statusInvalid: 'Not valid',
        expiredNote: 'Enterprise features are off. No data was deleted; install a renewed key to turn them back on.',
        invalidNote: 'The installed key can no longer be verified: {{error}}',
        remove: 'Remove license',
        removeConfirm: 'Remove the license key? Enterprise features switch off; no data is deleted.',
        removed: 'License removed',
        installTitle: 'Install a license key',
        installDesc: 'Paste the key or choose the file you received. Installing replaces the current key.',
        keyLabel: 'License key',
        fileLabel: 'Or choose a file',
        offlineHint: 'Keys are checked on this server, offline. Nothing is sent anywhere.',
        install: 'Install license',
        installed: 'License installed',
        installFailed: 'This license key could not be installed',
    },
    fr: {
        menuLabel: 'Licence Enterprise',
        title: 'Licence Enterprise',
        subtitle: 'SerOps Community est complet sans licence. Une clé de licence ajoute les fonctionnalités de gouvernance Enterprise.',
        currentTitle: 'Licence actuelle',
        currentDesc: 'Couvre toutes les organisations de cette installation.',
        none: 'Aucune licence installée. Toutes les fonctionnalités Community fonctionnent sans licence.',
        licensee: 'Titulaire',
        status: 'Statut',
        expires: "Valable jusqu'au",
        licenseId: 'Identifiant de licence',
        features: 'Fonctionnalités Enterprise',
        statusValid: 'Valide',
        statusExpired: 'Expirée',
        statusInvalid: 'Non valide',
        expiredNote: 'Les fonctionnalités Enterprise sont désactivées. Aucune donnée supprimée ; installez une clé renouvelée pour les réactiver.',
        invalidNote: 'La clé installée ne peut plus être vérifiée : {{error}}',
        remove: 'Retirer la licence',
        removeConfirm: 'Retirer la clé de licence ? Les fonctionnalités Enterprise sont désactivées ; aucune donnée supprimée.',
        removed: 'Licence retirée',
        installTitle: 'Installer une clé de licence',
        installDesc: 'Collez la clé ou choisissez le fichier reçu. Installer remplace la clé actuelle.',
        keyLabel: 'Clé de licence',
        fileLabel: 'Ou choisissez un fichier',
        offlineHint: 'Les clés sont vérifiées sur ce serveur, hors ligne. Rien n’est envoyé ailleurs.',
        install: 'Installer la licence',
        installed: 'Licence installée',
        installFailed: "Cette clé de licence n'a pas pu être installée",
    },
};

const add = () => Object.entries(strings).forEach(([lng, license]) => {
    i18n.addResourceBundle(lng, 'translation', { ee: { license } }, true, false);
});

if (i18n.isInitialized) add();
else i18n.on('initialized', add);
