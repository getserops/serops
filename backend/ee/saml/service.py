"""SAML 2.0 service provider, one per organisation (Enterprise, feature ``saml``).

Built on python3-saml (OneLogin's toolkit, MIT): it parses and validates
the XML, checks the XML signatures with xmlsec and decrypts encrypted
assertions. What it checks on every response, in strict mode: the
signature of the assertion (required here) with one of the identity
provider's certificates, issuer, audience (our entity ID), destination and
recipient (our ACS URL), NotBefore / NotOnOrAfter with the clock skew below,
and InResponseTo when we started the sign-in. On top of it, this module
adds what the toolkit leaves to the application: single use of each
assertion (replay), single use of each request we sent, a maximum age, and
whether sign-in started at the identity provider is allowed.

Accounts, roles and teams are not decided here: ``complete_sign_in`` in
Users/sso_views.py (Community) applies the organisation's SSO group
mapping, the same as for OpenID Connect.
"""
import datetime
import logging
import uuid
from urllib.parse import urlsplit

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.constants import OneLogin_Saml2_Constants
from onelogin.saml2.idp_metadata_parser import OneLogin_Saml2_IdPMetadataParser
from onelogin.saml2.response import OneLogin_Saml2_Response
from onelogin.saml2.settings import OneLogin_Saml2_Settings
from onelogin.saml2.utils import OneLogin_Saml2_Utils

logger = logging.getLogger(__name__)

# Allowed difference between the identity provider's clock and ours, on
# NotBefore / NotOnOrAfter. The toolkit reads this class attribute.
CLOCK_SKEW_SECONDS = int(getattr(settings, 'SAML_CLOCK_SKEW_SECONDS', 180))
OneLogin_Saml2_Constants.ALLOWED_CLOCK_DRIFT = CLOCK_SKEW_SECONDS

# An assertion is used within seconds of being issued; refuse older ones
# even if the identity provider gave them a longer validity.
MAX_ASSERTION_AGE_SECONDS = int(getattr(settings, 'SAML_MAX_ASSERTION_AGE_SECONDS', 600))

# How long a sign-in we started may take at the identity provider.
REQUEST_TTL_SECONDS = 900
METADATA_MAX_BYTES = 1024 * 1024

# Where identity providers usually put these, tried after the configured
# attribute name (Entra ID claim URIs, Okta/Keycloak plain names, OIDs).
EMAIL_ATTRIBUTES = (
    'http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress',
    'email', 'mail', 'emailAddress', 'urn:oid:0.9.2342.19200300.100.1.3',
)
FIRST_NAME_ATTRIBUTES = (
    'http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname',
    'firstName', 'givenName', 'first_name', 'urn:oid:2.5.4.42',
)
LAST_NAME_ATTRIBUTES = (
    'http://schemas.xmlsoap.org/ws/2005/05/identity/claims/surname',
    'lastName', 'sn', 'surname', 'last_name', 'urn:oid:2.5.4.4',
)
ENTRA_GROUPS_CLAIM = 'http://schemas.microsoft.com/ws/2008/06/identity/claims/groups'
ENTRA_GROUPS_OVERAGE = 'http://schemas.microsoft.com/claims/groups.link'


class SamlError(Exception):
    """A response or a configuration we refuse; the message is for the log only."""


# --- Our side: URLs and key pair -------------------------------------------

def _base(config):
    return f"{(settings.API_URL or '').rstrip('/')}/ee/saml/{config.sp_id}"


def sp_entity_id(config):
    """Our entity ID: the metadata URL (what Entra ID calls Identifier)."""
    return f'{_base(config)}/metadata/'


def acs_url(config):
    """Assertion Consumer Service: where the identity provider posts (Entra ID's Reply URL)."""
    return f'{_base(config)}/acs/'


def generate_keypair():
    """(certificate PEM, private key PEM): RSA 2048, self-signed, ten years.

    Only for encrypted assertions: the identity provider encrypts to this
    certificate. Self-signed is the norm for SAML metadata.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'SerOps SAML service provider')])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .sign(key, hashes.SHA256()))
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    return cert_pem, key_pem


def get_or_create_config(organisation):
    from Utils import crypto
    from ee.models import SamlConfig
    config = SamlConfig.objects.filter(organisation=organisation).first()
    if config is None:
        cert, key = generate_keypair()
        config = SamlConfig.objects.create(
            organisation=organisation, sp_id=uuid.uuid4(),
            sp_certificate=cert, sp_private_key_encrypted=crypto.encrypt(key),
        )
    return config


def _sp_private_key(config):
    from Utils import crypto
    if not config.sp_private_key_encrypted:
        return ''
    try:
        return crypto.decrypt(config.sp_private_key_encrypted)
    except crypto.DecryptionError:
        # The encryption key changed without rotate_secrets: encrypted
        # assertions cannot be read, signed ones still work.
        logger.error('SAML: the service provider key of org %s cannot be decrypted', config.organisation_id)
        return ''


def is_configured(config):
    return bool(config and config.idp_entity_id and config.idp_sso_url and config.idp_certificates)


def toolkit_settings(config, with_idp=True):
    """The python3-saml settings dict for this organisation."""
    data = {
        'strict': True,
        'debug': False,
        'sp': {
            'entityId': sp_entity_id(config),
            'assertionConsumerService': {
                'url': acs_url(config),
                'binding': OneLogin_Saml2_Constants.BINDING_HTTP_POST,
            },
            'NameIDFormat': OneLogin_Saml2_Constants.NAMEID_UNSPECIFIED,
            'x509cert': config.sp_certificate,
            'privateKey': _sp_private_key(config),
        },
        'security': {
            # Every assertion must carry the identity provider's signature;
            # a signed Response around an unsigned assertion is not enough.
            'wantAssertionsSigned': True,
            'wantMessagesSigned': False,
            'wantAssertionsEncrypted': bool(config.want_assertions_encrypted),
            'wantNameId': False,  # The email may come from an attribute.
            'wantAttributeStatement': False,
            'requestedAuthnContext': False,  # Let the identity provider choose MFA.
            'authnRequestsSigned': False,
            'rejectDeprecatedAlgorithm': True,  # No SHA-1 signatures.
            'rejectUnsolicitedResponsesWithInResponseTo': True,
            # Keycloak's group mapper sends one <Attribute Name="groups"> per
            # group; the toolkit then merges the values.
            'allowRepeatAttributeName': True,
            'signatureAlgorithm': OneLogin_Saml2_Constants.RSA_SHA256,
            'digestAlgorithm': OneLogin_Saml2_Constants.SHA256,
            # Lab installs and Keycloak in Docker use names like
            # "localhost" or "keycloak"; the URLs are checked on save.
            'allowSingleLabelDomains': True,
        },
    }
    if with_idp:
        data['idp'] = {
            'entityId': config.idp_entity_id,
            'singleSignOnService': {'url': config.idp_sso_url,
                                    'binding': OneLogin_Saml2_Constants.BINDING_HTTP_REDIRECT},
            'x509certMulti': {'signing': list(config.idp_certificates)},
        }
    return data


def metadata_xml(config):
    """Our SP metadata, to upload at the identity provider."""
    data = toolkit_settings(config, with_idp=False)
    # Always publish our certificate for encryption too, so an identity
    # provider that imports this file can encrypt; whether we require it
    # is the organisation's setting, enforced on each response.
    data['security']['wantAssertionsEncrypted'] = True
    saml_settings = OneLogin_Saml2_Settings(data, sp_validation_only=True)
    xml = saml_settings.get_sp_metadata()
    errors = saml_settings.validate_metadata(xml)
    if errors:
        raise SamlError(f'invalid SP metadata: {errors}')
    return xml.decode() if isinstance(xml, bytes) else xml


def _request_data(request, config, post_data=None):
    """What the toolkit calls the request: built from our ACS URL, not the Host header.

    Behind a proxy the Host and scheme Django sees can differ from the
    public URL the identity provider posted to; the destination check must
    compare against the public one.
    """
    url = urlsplit(acs_url(config))
    return {
        'https': 'on' if url.scheme == 'https' else 'off',
        'http_host': url.netloc,
        'script_name': url.path,
        'get_data': {},
        'post_data': post_data if post_data is not None else {},
    }


# --- Identity provider metadata ---------------------------------------------

def parse_idp_metadata(xml):
    """(entity ID, sign-in URL, signing certificates) from IdP metadata XML."""
    if isinstance(xml, str):
        xml = xml.encode()
    if len(xml) > METADATA_MAX_BYTES:
        raise SamlError('The metadata is larger than 1 MB')
    try:
        parsed = OneLogin_Saml2_IdPMetadataParser.parse(
            xml, required_sso_binding=OneLogin_Saml2_Constants.BINDING_HTTP_REDIRECT)
    except Exception as exc:
        raise SamlError(f'Not SAML identity provider metadata ({type(exc).__name__})') from exc
    idp = parsed.get('idp') or {}
    certs = list(((idp.get('x509certMulti') or {}).get('signing')) or [])
    if not certs and idp.get('x509cert'):
        certs = [idp['x509cert']]
    entity_id = idp.get('entityId') or ''
    sso_url = (idp.get('singleSignOnService') or {}).get('url') or ''
    if not entity_id or not sso_url or not certs:
        raise SamlError('The metadata has no entity ID, no HTTP-Redirect sign-in URL or no signing certificate')
    return entity_id, sso_url, [normalise_certificate(c) for c in certs]


def fetch_idp_metadata(url):
    """Download the metadata, with the same outbound checks as every admin-set URL."""
    from Utils.outbound import GuardedSession
    response = GuardedSession().get(url, timeout=10, stream=True)
    response.raise_for_status()
    body = response.raw.read(METADATA_MAX_BYTES + 1, decode_content=True)
    if len(body) > METADATA_MAX_BYTES:
        raise SamlError('The metadata is larger than 1 MB')
    return body


def normalise_certificate(text):
    """The base64 body of a PEM certificate, checked to be one."""
    from cryptography import x509
    body = ''.join(line.strip() for line in str(text).strip().splitlines()
                   if line.strip() and not line.startswith('-----'))
    pem = OneLogin_Saml2_Utils.format_cert(body)
    try:
        x509.load_pem_x509_certificate(pem.encode())
    except ValueError as exc:
        raise SamlError('Not an X.509 certificate') from exc
    return body


def certificate_summary(body):
    """Subject, expiry and SHA-256 fingerprint, for the settings page."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    cert = x509.load_pem_x509_certificate(OneLogin_Saml2_Utils.format_cert(body).encode())
    return {
        'subject': cert.subject.rfc4514_string(),
        'expires': cert.not_valid_after_utc.isoformat(),
        'sha256': cert.fingerprint(hashes.SHA256()).hex(':').upper(),
    }


# --- Sign-in ----------------------------------------------------------------

def _request_key(request_id):
    return f'ee:saml:request:{request_id}'


def start_login(request, sec_settings):
    """The identity provider URL that starts a sign-in (HTTP-Redirect binding)."""
    from ee.models import SamlConfig
    config = SamlConfig.objects.filter(organisation_id=sec_settings.organisation_id).first()
    if not is_configured(config):
        raise SamlError('SAML is on but the identity provider is not configured')
    auth = OneLogin_Saml2_Auth(_request_data(request, config), toolkit_settings(config))
    url = auth.login()
    # Remembered server-side, so the response must answer a request we
    # sent, once. (A cookie cannot do it: the identity provider posts
    # cross-site, and SameSite=None cookies need https, which lab installs
    # may not have.)
    cache.set(_request_key(auth.get_last_request_id()), sec_settings.organisation_id, REQUEST_TTL_SECONDS)
    return url


def _first(attributes, names):
    for name in names:
        values = attributes.get(name) if name else None
        if values:
            value = values[0] if isinstance(values, list) else values
            if value:
                return str(value).strip()
    return ''


class Identity:
    def __init__(self, email, first_name, last_name, groups, assertion_id):
        self.email = email
        self.first_name = first_name
        self.last_name = last_name
        self.groups = groups
        self.assertion_id = assertion_id


def process_response(config, sec_settings, saml_response):
    """Validate a posted SAMLResponse; the identity it asserts, or SamlError.

    ``saml_response`` is the base64 form field as posted.
    """
    saml_settings = OneLogin_Saml2_Settings(toolkit_settings(config))
    try:
        in_response_to = OneLogin_Saml2_Response(saml_settings, saml_response).get_in_response_to()
    except Exception as exc:
        raise SamlError(f'unreadable response ({type(exc).__name__}: {exc})') from exc

    if in_response_to:
        # Answers a request we sent: it must be ours, for this
        # organisation, and is consumed now.
        key = _request_key(in_response_to)
        if cache.get(key) != config.organisation_id or not cache.delete(key):
            raise SamlError('InResponseTo names no pending request of this organisation')
    elif not config.allow_idp_initiated:
        raise SamlError('sign-in started at the identity provider, which this organisation does not allow')

    auth = OneLogin_Saml2_Auth(_request_data(None, config, {'SAMLResponse': saml_response}), saml_settings)
    auth.process_response(request_id=in_response_to or None)
    if auth.get_errors() or not auth.is_authenticated():
        raise SamlError(f'invalid response: {auth.get_last_error_reason() or auth.get_errors()}')

    assertion_id = auth.get_last_assertion_id()
    issued = auth.get_last_assertion_issue_instant()
    if not assertion_id or not issued:
        raise SamlError('the assertion has no ID or no IssueInstant')
    now = timezone.now().timestamp()
    if issued + MAX_ASSERTION_AGE_SECONDS + CLOCK_SKEW_SECONDS < now:
        raise SamlError('the assertion is older than the maximum age')
    _consume_assertion(config, assertion_id, issued)

    attributes = auth.get_attributes()
    nameid = (auth.get_nameid() or '').strip()
    email = _first(attributes, (config.email_attribute, *EMAIL_ATTRIBUTES))
    if not email and '@' in nameid:
        email = nameid
    if not email or '@' not in email:
        raise SamlError('the assertion has no email address (NameID or attribute)')
    groups_attribute = sec_settings.sso_groups_claim or 'groups'
    groups = [str(g) for g in (attributes.get(groups_attribute) or []) if g]
    if not groups and attributes.get(ENTRA_GROUPS_OVERAGE):
        logger.warning('SAML: Entra ID sent a groups link instead of groups (more than 150); '
                       'assign only the needed groups to the application (org %s)', config.organisation_id)
    return Identity(
        email=email,
        first_name=_first(attributes, (config.first_name_attribute, *FIRST_NAME_ATTRIBUTES)),
        last_name=_first(attributes, (config.last_name_attribute, *LAST_NAME_ATTRIBUTES)),
        groups=groups,
        assertion_id=assertion_id,
    )


def _consume_assertion(config, assertion_id, issued):
    """Record the assertion as used; SamlError if it was used before."""
    from ee.models import SamlAssertion
    now = timezone.now()
    expires = datetime.datetime.fromtimestamp(
        issued + MAX_ASSERTION_AGE_SECONDS + 2 * CLOCK_SKEW_SECONDS, tz=datetime.timezone.utc)
    SamlAssertion.objects.filter(expires_at__lt=now).delete()
    try:
        with transaction.atomic():
            SamlAssertion.objects.create(assertion_id=assertion_id[:256], organisation_id=config.organisation_id,
                                         expires_at=expires)
    except IntegrityError as exc:
        raise SamlError('assertion already used (replay)') from exc


class SamlProtocol:
    """Registered with Utils.edition so Community's SSO init can start SAML."""

    feature = 'saml'

    def start(self, request, sec_settings):
        return start_login(request, sec_settings)
