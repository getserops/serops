from django.conf import settings
from django.db import models


class InstalledLicense(models.Model):
    """The Enterprise license key of this install (at most one row).

    Install-wide: one install can host several organisations, and the key
    covers all of them. Removing the row, or the key expiring, switches the
    Enterprise features off; no other data depends on it.
    """

    raw = models.TextField(help_text='The license key exactly as uploaded (signed JSON).')
    installed_at = models.DateTimeField(auto_now=True)
    installed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )

    def __str__(self):
        return f'Enterprise license (installed {self.installed_at:%Y-%m-%d})'


class SamlConfig(models.Model):
    """SAML 2.0 sign-in of one organisation (Enterprise, feature ``saml``).

    The identity provider's side (entity ID, sign-in URL, signing
    certificates) comes from its metadata. Our side is per organisation:
    ``sp_id`` names it in every URL (entity ID, ACS, metadata), so it never
    changes when the organisation is renamed, and the key pair lets the
    identity provider encrypt assertions to us. Who gets which role and team
    is the SSO group mapping in ``SecuritySettings``, shared with OIDC.
    """

    organisation = models.OneToOneField(
        'Organisations.Organisations', on_delete=models.CASCADE, related_name='saml_config',
    )
    sp_id = models.UUIDField(unique=True, editable=False)

    idp_metadata_url = models.URLField(max_length=1024, blank=True, default='')
    idp_entity_id = models.CharField(max_length=1024, blank=True, default='')
    idp_sso_url = models.URLField(max_length=1024, blank=True, default='')
    # PEM bodies of the certificates that may sign assertions (several during
    # a certificate rollover at the identity provider).
    idp_certificates = models.JSONField(default=list, blank=True)
    idp_metadata_fetched_at = models.DateTimeField(null=True, blank=True)

    # Our key pair, for encrypted assertions. The private key is stored
    # encrypted with SEROPS_ENCRYPTION_KEY (Utils/crypto.py).
    sp_certificate = models.TextField(blank=True, default='')
    sp_private_key_encrypted = models.TextField(blank=True, default='')

    # Attribute names in the assertion. Empty email attribute: the NameID,
    # when it is an email address. The groups attribute is the SSO
    # "groups claim" of SecuritySettings.
    email_attribute = models.CharField(max_length=512, blank=True, default='')
    first_name_attribute = models.CharField(max_length=512, blank=True, default='')
    last_name_attribute = models.CharField(max_length=512, blank=True, default='')

    want_assertions_encrypted = models.BooleanField(default=False)
    # Sign-in started from the identity provider's portal (Entra ID "My
    # Apps", an Okta tile), with no request from us to answer.
    allow_idp_initiated = models.BooleanField(default=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'SAML for organisation {self.organisation_id}'


class SamlAssertion(models.Model):
    """Assertions already used, so the same one cannot sign in twice.

    Kept until the assertion would have expired anyway (plus the allowed
    clock skew); older rows are deleted as new ones arrive.
    """

    assertion_id = models.CharField(max_length=256, unique=True)
    organisation = models.ForeignKey('Organisations.Organisations', on_delete=models.CASCADE, related_name='+')
    expires_at = models.DateTimeField(db_index=True)


class ScimToken(models.Model):
    """Bearer token an identity provider uses to provision one organisation (feature ``scim``).

    Shown once when created; only its SHA-256 is stored. Revoking keeps the
    row (who created it, when it was last used) for the audit trail.
    """

    organisation = models.ForeignKey('Organisations.Organisations', on_delete=models.CASCADE,
                                     related_name='scim_tokens')
    name = models.CharField(max_length=100)
    token_hash = models.CharField(max_length=64, unique=True)
    prefix = models.CharField(max_length=16, help_text='First characters, to recognise the token in the list.')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)


class ScimIdentity(models.Model):
    """A SerOps account as the identity provider sees it through SCIM.

    ``scim_id`` is the SCIM ``id`` (never the database key); ``active`` is
    what the identity provider last said, kept apart from ``User.is_active``,
    which also depends on the group rules.
    """

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='scim_identity')
    organisation = models.ForeignKey('Organisations.Organisations', on_delete=models.CASCADE, related_name='+')
    scim_id = models.UUIDField(unique=True)
    user_name = models.CharField(max_length=255)
    external_id = models.CharField(max_length=255, blank=True, default='')
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organisation', 'user_name'], name='scim_identity_user_name')]


class ScimGroup(models.Model):
    """A group pushed by the identity provider. Its members get the roles and
    teams of the SSO group rules, matched on its name or its external ID."""

    organisation = models.ForeignKey('Organisations.Organisations', on_delete=models.CASCADE, related_name='+')
    scim_id = models.UUIDField(unique=True)
    display_name = models.CharField(max_length=255)
    external_id = models.CharField(max_length=255, blank=True, default='')
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='scim_groups', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organisation', 'display_name'], name='scim_group_name')]


class AuditStreamDestination(models.Model):
    """Where an organisation's audit events are streamed (feature ``audit_streaming``).

    ``http``: events POSTed in batches (JSON array, NDJSON or Splunk HEC),
    with an optional authorization header and HMAC signature. ``syslog``:
    RFC 5424 messages over TCP with TLS (octet counting, RFC 5425), plain
    TCP or UDP. Secrets are encrypted with SEROPS_ENCRYPTION_KEY.
    """

    KIND_HTTP = 'http'
    KIND_SYSLOG = 'syslog'
    KINDS = [(KIND_HTTP, 'HTTPS'), (KIND_SYSLOG, 'Syslog')]
    FORMATS = [('json', 'JSON array'), ('ndjson', 'Newline-delimited JSON'), ('splunk_hec', 'Splunk HEC')]
    TRANSPORTS = [('tls', 'TCP with TLS'), ('tcp', 'TCP'), ('udp', 'UDP')]

    organisation = models.ForeignKey('Organisations.Organisations', on_delete=models.CASCADE,
                                     related_name='audit_stream_destinations')
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=KINDS)
    enabled = models.BooleanField(default=True)

    # http
    url = models.URLField(max_length=1024, blank=True, default='')
    http_format = models.CharField(max_length=20, choices=FORMATS, default='json')
    auth_header_name = models.CharField(max_length=100, blank=True, default='')
    auth_header_value_encrypted = models.TextField(blank=True, default='')
    signing_secret_encrypted = models.TextField(blank=True, default='')

    # TLS, both kinds: the CA that signed the collector's certificate.
    ca_certificate = models.TextField(blank=True, default='', help_text='PEM; empty uses the system CAs.')

    # syslog
    host = models.CharField(max_length=255, blank=True, default='')
    port = models.PositiveIntegerField(null=True, blank=True)
    transport = models.CharField(max_length=10, choices=TRANSPORTS, default='tls')

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_failure_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True, default='')
    delivered_count = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organisation', 'name'], name='ee_audit_stream_unique_name')]

    def __str__(self):
        return f'{self.name} ({self.kind})'


class AuditStreamPending(models.Model):
    """An audit event not yet delivered to a destination (transactional outbox).

    Created in the same transaction as the audit entry, so an event is
    queued if and only if it was recorded; deleted once delivered. Deleted
    with the audit entry too (retention), never left dangling.
    """

    destination = models.ForeignKey(AuditStreamDestination, on_delete=models.CASCADE, related_name='pending')
    audit_log = models.ForeignKey('Data.AuditLog', on_delete=models.CASCADE, related_name='+')
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['destination', 'audit_log'],
                                               name='ee_audit_stream_pending_once')]
        indexes = [models.Index(fields=['destination', 'next_attempt_at', 'audit_log'])]
