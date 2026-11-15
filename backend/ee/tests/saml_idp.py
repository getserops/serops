"""A test identity provider: SAML responses signed (and encrypted) like real ones.

Builds the XML that Entra ID, Okta and Keycloak post, so the tests run the
real signature, decryption and condition checks of the toolkit.
"""
import base64
import datetime
import uuid

from onelogin.saml2.constants import OneLogin_Saml2_Constants as C
from onelogin.saml2.utils import OneLogin_Saml2_Utils

from ee.saml.service import generate_keypair

ENTITY_ID = 'https://idp.example.test/saml'
SSO_URL = 'https://idp.example.test/saml/sso'


def _ts(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def cert_body(pem):
    return ''.join(line for line in pem.strip().splitlines() if not line.startswith('-----'))


class TestIdP:
    def __init__(self):
        self.cert, self.key = generate_keypair()

    def metadata(self, entity_id=ENTITY_ID, sso_url=SSO_URL):
        return f'''<?xml version="1.0"?>
<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID="{entity_id}">
  <md:IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <md:KeyDescriptor use="signing"><ds:KeyInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#">
      <ds:X509Data><ds:X509Certificate>{cert_body(self.cert)}</ds:X509Certificate></ds:X509Data>
    </ds:KeyInfo></md:KeyDescriptor>
    <md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" Location="{sso_url}"/>
  </md:IDPSSODescriptor>
</md:EntityDescriptor>'''

    def response(self, *, acs, audience, email='ada@acme.test', groups=(), in_response_to=None,
                 issuer=ENTITY_ID, issued=None, lifetime=300, sign_assertion=True, sign_response=False,
                 encrypt_to=None, destination=None, nameid=None, attributes=None, assertion_id=None,
                 groups_attribute='groups', key=None, cert=None, digest_sha1=False):
        """A base64 SAMLResponse, as the browser posts it."""
        issued = issued or _now()
        expires = issued + datetime.timedelta(seconds=lifetime)
        irt = f' InResponseTo="{in_response_to}"' if in_response_to else ''
        assertion_id = assertion_id or f'_a{uuid.uuid4().hex}'
        attrs = dict(attributes or {})
        if groups:
            attrs[groups_attribute] = list(groups)
        attr_xml = ''.join(
            f'<saml:Attribute Name="{name}">' + ''.join(
                f'<saml:AttributeValue xsi:type="xs:string">{v}</saml:AttributeValue>' for v in
                (values if isinstance(values, (list, tuple)) else [values])) + '</saml:Attribute>'
            for name, values in attrs.items())
        nameid = email if nameid is None else nameid
        assertion = f'''<saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" ID="{assertion_id}" Version="2.0" IssueInstant="{_ts(issued)}"><saml:Issuer>{issuer}</saml:Issuer><saml:Subject><saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">{nameid}</saml:NameID><saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer"><saml:SubjectConfirmationData NotOnOrAfter="{_ts(expires)}" Recipient="{acs}"{irt}/></saml:SubjectConfirmation></saml:Subject><saml:Conditions NotBefore="{_ts(issued - datetime.timedelta(seconds=30))}" NotOnOrAfter="{_ts(expires)}"><saml:AudienceRestriction><saml:Audience>{audience}</saml:Audience></saml:AudienceRestriction></saml:Conditions><saml:AuthnStatement AuthnInstant="{_ts(issued)}" SessionIndex="_s{uuid.uuid4().hex}"><saml:AuthnContext><saml:AuthnContextClassRef>urn:oasis:names:tc:SAML:2.0:ac:classes:Password</saml:AuthnContextClassRef></saml:AuthnContext></saml:AuthnStatement>{'<saml:AttributeStatement>' + attr_xml + '</saml:AttributeStatement>' if attr_xml else ''}</saml:Assertion>'''
        key, cert = key or self.key, cert or self.cert
        digest = C.SHA1 if digest_sha1 else C.SHA256
        algorithm = C.RSA_SHA1 if digest_sha1 else C.RSA_SHA256
        if sign_assertion:
            assertion = OneLogin_Saml2_Utils.add_sign(assertion, key, cert, sign_algorithm=algorithm,
                                                      digest_algorithm=digest).decode()
        if encrypt_to:
            assertion = encrypt(assertion, encrypt_to)
        destination = acs if destination is None else destination
        response = f'''<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="_r{uuid.uuid4().hex}" Version="2.0" IssueInstant="{_ts(issued)}" Destination="{destination}"{irt}><saml:Issuer>{issuer}</saml:Issuer><samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>{assertion}</samlp:Response>'''
        if sign_response:
            response = OneLogin_Saml2_Utils.add_sign(response, key, cert, sign_algorithm=algorithm,
                                                     digest_algorithm=digest).decode()
        return base64.b64encode(response.encode()).decode()


def encrypt(assertion_xml, sp_cert_pem):
    """<saml:EncryptedAssertion> of the assertion, to the SP certificate (AES-256-CBC, RSA-OAEP)."""
    import xmlsec
    from lxml import etree
    wrapper = etree.fromstring(
        '<saml:EncryptedAssertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"></saml:EncryptedAssertion>')
    assertion = etree.fromstring(assertion_xml.encode())
    wrapper.append(assertion)
    enc_data = xmlsec.template.encrypted_data_create(
        wrapper, xmlsec.constants.TransformAes256Cbc, type=xmlsec.constants.TypeEncElement, ns='xenc')
    xmlsec.template.encrypted_data_ensure_cipher_value(enc_data)
    key_info = xmlsec.template.encrypted_data_ensure_key_info(enc_data, ns='dsig')
    enc_key = xmlsec.template.add_encrypted_key(key_info, xmlsec.constants.TransformRsaOaep)
    xmlsec.template.encrypted_data_ensure_cipher_value(enc_key)
    manager = xmlsec.KeysManager()
    manager.add_key(xmlsec.Key.from_memory(sp_cert_pem.encode(), xmlsec.constants.KeyDataFormatCertPem, None))
    ctx = xmlsec.EncryptionContext(manager)
    ctx.key = xmlsec.Key.generate(xmlsec.constants.KeyDataAes, 256, xmlsec.constants.KeyDataTypeSession)
    ctx.encrypt_xml(enc_data, assertion)
    return etree.tostring(wrapper).decode()
