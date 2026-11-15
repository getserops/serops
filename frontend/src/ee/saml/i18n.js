// The shared i18next instance (initialised in src/i18n.js); bundles are added
// once it is ready, whatever the import order.
import i18n from 'i18next';

export const strings = {
    en: {
        registerTitle: 'Register SerOps at your identity provider',
        registerDesc: 'Create a SAML application there with these values, or upload the metadata file.',
        entityId: 'Identifier (Entity ID)',
        acsUrl: 'Reply URL (Assertion Consumer Service URL)',
        metadataUrl: 'Metadata',
        downloadMetadata: 'Download metadata',
        idpTitle: 'Your identity provider',
        idpDesc: 'Paste its federation metadata URL (Entra ID: App Federation Metadata Url). SerOps reads the sign-in URL and the signing certificates from it.',
        idpMetadataUrl: 'Metadata URL',
        idpMetadataXml: 'Or paste the metadata XML',
        refresh: 'Read the metadata again',
        refreshHint: 'After the identity provider rotates its certificate.',
        idpEntityId: 'Identity provider entity ID',
        idpSsoUrl: 'Sign-in URL',
        certificates: 'Signing certificates',
        expires: 'expires {{date}}',
        notConfigured: 'Not configured yet: SAML sign-in is refused until the metadata is read.',
        attributesTitle: 'Attributes',
        attributesDesc: 'Leave empty for the usual names (Entra ID claim URIs, email, firstName, lastName). The email comes from the NameID when it is an address.',
        emailAttribute: 'Email attribute',
        firstNameAttribute: 'First name attribute',
        lastNameAttribute: 'Last name attribute',
        optionsTitle: 'Security',
        idpInitiated: 'Allow sign-in started from the identity provider',
        idpInitiatedHint: 'From the Entra ID My Apps portal or an Okta tile. Off: only sign-ins started on the SerOps login page are accepted.',
        encrypted: 'Require encrypted assertions',
        encryptedHint: 'The identity provider encrypts assertions to the certificate below. Encrypted assertions are always accepted; this refuses the others.',
        spCertificate: 'SerOps encryption certificate',
        signedNote: 'Assertions must be signed by your identity provider (SHA-256). Each one is accepted once, within {{skew}} seconds of clock difference. Single logout is not supported: signing out of SerOps does not sign out of the identity provider.',
        loadFailed: 'Could not load the SAML settings',
        saveFailed: 'Could not save the SAML settings',
    },
    fr: {
        registerTitle: "Déclarer SerOps chez votre fournisseur d'identité",
        registerDesc: 'Créez-y une application SAML avec ces valeurs, ou importez le fichier de métadonnées.',
        entityId: 'Identifiant (Entity ID)',
        acsUrl: 'URL de réponse (Assertion Consumer Service)',
        metadataUrl: 'Métadonnées',
        downloadMetadata: 'Télécharger les métadonnées',
        idpTitle: "Votre fournisseur d'identité",
        idpDesc: "Collez l'URL de ses métadonnées de fédération (Entra ID : URL des métadonnées de fédération d'application). SerOps y lit l'URL de connexion et les certificats de signature.",
        idpMetadataUrl: 'URL des métadonnées',
        idpMetadataXml: 'Ou collez le XML des métadonnées',
        refresh: 'Relire les métadonnées',
        refreshHint: "Après un renouvellement de certificat chez le fournisseur d'identité.",
        idpEntityId: "Entity ID du fournisseur d'identité",
        idpSsoUrl: 'URL de connexion',
        certificates: 'Certificats de signature',
        expires: 'expire le {{date}}',
        notConfigured: 'Pas encore configuré : la connexion SAML est refusée tant que les métadonnées ne sont pas lues.',
        attributesTitle: 'Attributs',
        attributesDesc: "Laissez vide pour les noms usuels (URI des revendications Entra ID, email, firstName, lastName). L'email vient du NameID quand c'est une adresse.",
        emailAttribute: "Attribut de l'email",
        firstNameAttribute: 'Attribut du prénom',
        lastNameAttribute: 'Attribut du nom',
        optionsTitle: 'Sécurité',
        idpInitiated: "Accepter les connexions lancées depuis le fournisseur d'identité",
        idpInitiatedHint: "Depuis le portail Mes applications d'Entra ID ou une tuile Okta. Désactivé : seules les connexions lancées depuis la page de connexion SerOps sont acceptées.",
        encrypted: 'Exiger des assertions chiffrées',
        encryptedHint: "Le fournisseur d'identité chiffre les assertions avec le certificat ci-dessous. Les assertions chiffrées sont toujours acceptées ; ceci refuse les autres.",
        spCertificate: 'Certificat de chiffrement SerOps',
        signedNote: "Les assertions doivent être signées par votre fournisseur d'identité (SHA-256). Chacune n'est acceptée qu'une fois, avec {{skew}} secondes d'écart d'horloge toléré. La déconnexion unique (SLO) n'est pas prise en charge : se déconnecter de SerOps ne déconnecte pas du fournisseur d'identité.",
        loadFailed: 'Impossible de charger les paramètres SAML',
        saveFailed: "Impossible d'enregistrer les paramètres SAML",
    },
};

const add = () => Object.entries(strings).forEach(([lng, saml]) => {
    i18n.addResourceBundle(lng, 'translation', { ee: { saml } }, true, false);
});

if (i18n.isInitialized) add();
else i18n.on('initialized', add);
