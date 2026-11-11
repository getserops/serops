// Strings of the Enterprise access module (shared i18next instance, see
// ../license/i18n.js). Role and project-access labels are the app's own.
import i18n from 'i18next';

export const strings = {
    en: {
        rolesUnlicensed: 'Custom roles are part of SerOps Enterprise. Without a license, the roles below keep working for the members who have them; you can move members to a built-in role and delete unused roles.',
        accessUnlicensed: 'Restricting projects to teams is part of SerOps Enterprise. Without a license, current restrictions keep applying; you can lower or remove team access and open the project to the organisation.',
        licenseLink: 'Enterprise license',
    },
    fr: {
        rolesUnlicensed: 'Les rôles personnalisés font partie de SerOps Enterprise. Sans licence, les rôles ci-dessous restent actifs pour les membres qui les ont ; vous pouvez passer ces membres à un rôle intégré et supprimer les rôles inutilisés.',
        accessUnlicensed: 'Réserver des projets à des équipes fait partie de SerOps Enterprise. Sans licence, les restrictions actuelles continuent de s’appliquer ; vous pouvez réduire ou retirer l’accès des équipes et ouvrir le projet à toute l’organisation.',
        licenseLink: 'Licence Enterprise',
    },
};

const add = () => Object.entries(strings).forEach(([lng, access]) => {
    i18n.addResourceBundle(lng, 'translation', { ee: { access } }, true, false);
});

if (i18n.isInitialized) add();
else i18n.on('initialized', add);
