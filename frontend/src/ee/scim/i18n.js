// The shared i18next instance (initialised in src/i18n.js); bundles are added
// once it is ready, whatever the import order.
import i18n from 'i18next';

export const strings = {
    en: {
        connectTitle: 'Connect your identity provider',
        connectDesc: 'In Entra ID (Enterprise application → Provisioning) or Okta (Provisioning → Integration), enter this tenant URL and a token created below.',
        baseUrl: 'Tenant URL (SCIM base URL)',
        tokensTitle: 'Tokens',
        tokensDesc: 'A token lets the identity provider create accounts, give roles and deactivate people in this organisation. Only admins manage them.',
        tokenName: 'Name',
        tokenNamePlaceholder: 'e.g. Entra ID',
        create: 'Create a token',
        creating: 'Creating…',
        newToken: 'Copy this token now and paste it in your identity provider: it is shown only once.',
        prefix: 'Starts with',
        createdAt: 'Created',
        lastUsed: 'Last used',
        never: 'never',
        status: 'Status',
        active: 'Active',
        revoked: 'Revoked',
        revoke: 'Revoke',
        revokeConfirm: 'Revoke the token "{{name}}"? The identity provider stops syncing at once.',
        noTokens: 'No token yet.',
        rulesNote: 'Roles and teams follow the group rules of Single sign-on above. With "Refuse sign-in" as the default role, someone the identity provider removes from every mapped group is deactivated at once and their sessions end.',
        loadFailed: 'Could not load the SCIM settings',
        createFailed: 'Could not create the token',
        revokeFailed: 'Could not revoke the token',
    },
    fr: {
        connectTitle: "Connecter votre fournisseur d'identité",
        connectDesc: "Dans Entra ID (Application d'entreprise → Approvisionnement) ou Okta (Provisioning → Integration), saisissez cette URL de locataire et un jeton créé ci-dessous.",
        baseUrl: 'URL du locataire (URL de base SCIM)',
        tokensTitle: 'Jetons',
        tokensDesc: "Un jeton permet au fournisseur d'identité de créer des comptes, d'attribuer des rôles et de désactiver des personnes dans cette organisation. Seuls les administrateurs les gèrent.",
        tokenName: 'Nom',
        tokenNamePlaceholder: 'ex. Entra ID',
        create: 'Créer un jeton',
        creating: 'Création…',
        newToken: "Copiez ce jeton maintenant et collez-le dans votre fournisseur d'identité : il n'est affiché qu'une fois.",
        prefix: 'Commence par',
        createdAt: 'Créé',
        lastUsed: 'Dernière utilisation',
        never: 'jamais',
        status: 'État',
        active: 'Actif',
        revoked: 'Révoqué',
        revoke: 'Révoquer',
        revokeConfirm: "Révoquer le jeton « {{name}} » ? Le fournisseur d'identité cesse aussitôt de synchroniser.",
        noTokens: 'Aucun jeton pour le moment.',
        rulesNote: "Les rôles et les équipes suivent les règles de groupes de l'authentification unique ci-dessus. Avec « Refuser la connexion » comme rôle par défaut, une personne que le fournisseur d'identité retire de tous les groupes associés est désactivée aussitôt et ses sessions prennent fin.",
        loadFailed: 'Impossible de charger les paramètres SCIM',
        createFailed: 'Impossible de créer le jeton',
        revokeFailed: 'Impossible de révoquer le jeton',
    },
};

const add = () => Object.entries(strings).forEach(([lng, scim]) => {
    i18n.addResourceBundle(lng, 'translation', { ee: { scim } }, true, false);
});

if (i18n.isInitialized) add();
else i18n.on('initialized', add);
