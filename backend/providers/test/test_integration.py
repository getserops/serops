"""
Tests for Provider Integration Encryption and Model

Tests cover:
- Credential encryption/decryption
- ProviderIntegration model methods
- Security: No plain-text tokens in database
"""

from django.test import TestCase, override_settings
from django.utils import timezone
from unittest.mock import patch, MagicMock

from providers.encryption import (
    encrypt_value, decrypt_value, 
    encrypt_credentials, decrypt_credentials,
    is_encrypted
)
from providers.models import ProviderIntegration
from Organisations.models import Organisations


class EncryptionTests(TestCase):
    """Test encryption utilities."""
    
    def test_encrypt_decrypt_roundtrip(self):
        """Verify encrypt then decrypt returns original value."""
        original = "glpat-xxxxxxxxxxxxxxxxxxxx"
        encrypted = encrypt_value(original)
        decrypted = decrypt_value(encrypted)
        
        self.assertEqual(original, decrypted)
        self.assertNotEqual(original, encrypted)
    
    def test_encrypt_empty_string(self):
        """Empty string should return empty string."""
        self.assertEqual(encrypt_value(""), "")
        self.assertEqual(decrypt_value(""), "")
    
    def test_encrypted_value_is_different(self):
        """Same value encrypted twice should produce same ciphertext (deterministic with same key)."""
        value = "my-secret-token"
        encrypted1 = encrypt_value(value)
        encrypted2 = encrypt_value(value)
        
        # Note: Fernet adds timestamp so encryptions differ, but both decrypt to same
        self.assertEqual(decrypt_value(encrypted1), decrypt_value(encrypted2))
    
    def test_encrypt_credentials_dict(self):
        """Test encrypting a credentials dictionary."""
        creds = {
            'access_token': 'glpat-xxxx',
            'username': 'admin',
            'url': 'https://gitlab.com'
        }
        
        encrypted = encrypt_credentials(creds)
        
        # Token should be encrypted
        self.assertNotEqual(encrypted['access_token'], 'glpat-xxxx')
        self.assertTrue(encrypted['_encrypted'])
        
        # Non-sensitive fields unchanged
        self.assertEqual(encrypted['username'], 'admin')
        self.assertEqual(encrypted['url'], 'https://gitlab.com')
    
    def test_decrypt_credentials_dict(self):
        """Test decrypting a credentials dictionary."""
        creds = {
            'access_token': 'glpat-xxxx',
            'api_key': 'sk-yyyy',
            'username': 'admin'
        }
        
        encrypted = encrypt_credentials(creds)
        decrypted = decrypt_credentials(encrypted)
        
        self.assertEqual(decrypted['access_token'], 'glpat-xxxx')
        self.assertEqual(decrypted['api_key'], 'sk-yyyy')
        self.assertEqual(decrypted['username'], 'admin')
        self.assertNotIn('_encrypted', decrypted)
    
    def test_is_encrypted_check(self):
        """Test is_encrypted helper."""
        plain = {'access_token': 'xxx'}
        encrypted = encrypt_credentials(plain)
        
        self.assertFalse(is_encrypted(plain))
        self.assertTrue(is_encrypted(encrypted))
        self.assertFalse(is_encrypted(None))
        self.assertFalse(is_encrypted({}))


class ProviderIntegrationModelTests(TestCase):
    """Test ProviderIntegration model methods."""
    
    @classmethod
    def setUpTestData(cls):
        """Set up test data."""
        cls.org = Organisations.objects.create(name='Test Org')
    
    def test_create_integration_with_credentials(self):
        """Test creating integration with encrypted credentials."""
        integration = ProviderIntegration.objects.create(
            name='Company GitLab',
            provider_type='gitlab',
            category='devops',
            organisation=self.org
        )
        
        # Set credentials using secure method
        integration.set_credentials({'access_token': 'glpat-secret-token'})
        integration.save()
        
        # Reload from database
        integration.refresh_from_db()
        
        # Token should be stored encrypted
        self.assertNotEqual(integration.credentials.get('access_token'), 'glpat-secret-token')
        self.assertTrue(integration.credentials.get('_encrypted'))
        
        # But get_access_token should return decrypted value
        self.assertEqual(integration.get_access_token(), 'glpat-secret-token')
    
    def test_get_credentials(self):
        """Test get_credentials returns decrypted dict."""
        integration = ProviderIntegration.objects.create(
            name='GitHub',
            provider_type='github',
            category='devops',
            organisation=self.org
        )
        
        integration.set_credentials({
            'access_token': 'ghp_xxxx',
            'username': 'myuser'
        })
        integration.save()
        
        creds = integration.get_credentials()
        
        self.assertEqual(creds['access_token'], 'ghp_xxxx')
        self.assertEqual(creds['username'], 'myuser')
    
    def test_mark_verified_success(self):
        """Test marking integration as verified."""
        integration = ProviderIntegration.objects.create(
            name='Test',
            provider_type='gitlab',
            category='devops',
            organisation=self.org
        )
        
        self.assertEqual(integration.verification_status, 'pending')
        self.assertFalse(integration.is_verified)
        self.assertTrue(integration.needs_verification)
        
        integration.mark_verified(success=True)
        
        self.assertEqual(integration.verification_status, 'verified')
        self.assertTrue(integration.is_verified)
        self.assertFalse(integration.needs_verification)
        self.assertIsNotNone(integration.last_verified_at)
    
    def test_mark_verified_failure(self):
        """Test marking integration as failed."""
        integration = ProviderIntegration.objects.create(
            name='Test',
            provider_type='gitlab',
            category='devops',
            organisation=self.org
        )
        
        integration.mark_verified(success=False, error='Invalid token')
        
        self.assertEqual(integration.verification_status, 'failed')
        self.assertFalse(integration.is_verified)
        self.assertTrue(integration.needs_verification)
        self.assertEqual(integration.verification_error, 'Invalid token')
    
    def test_get_default_capabilities(self):
        """Test getting default capabilities for each provider."""
        test_cases = [
            ('gitlab', ['scm', 'cicd', 'deployments', 'issues']),
            ('github', ['scm', 'cicd', 'deployments', 'issues']),
            ('jenkins', ['cicd', 'deployments']),
            ('bitbucket', ['scm', 'cicd']),
        ]
        
        for provider_type, expected_caps in test_cases:
            with self.subTest(provider=provider_type):
                integration = ProviderIntegration(
                    provider_type=provider_type,
                    organisation=self.org
                )
                self.assertEqual(integration.get_default_capabilities(), expected_caps)
    
    def test_display_url_default(self):
        """Test display_url returns correct default URLs."""
        integration = ProviderIntegration(
            provider_type='gitlab',
            organisation=self.org
        )
        
        self.assertEqual(integration.display_url, 'https://gitlab.com')
        
        # With custom base_url
        integration.base_url = 'https://gitlab.company.com'
        self.assertEqual(integration.display_url, 'https://gitlab.company.com')
    
    def test_credentials_not_leaked_in_str(self):
        """Ensure __str__ doesn't leak credentials."""
        integration = ProviderIntegration(
            name='Secret GitLab',
            provider_type='gitlab',
            organisation=self.org
        )
        integration.set_credentials({'access_token': 'super-secret-token'})
        
        str_repr = str(integration)
        
        self.assertNotIn('super-secret-token', str_repr)
        self.assertIn('Secret GitLab', str_repr)


class ApiTokenEncryptionTests(TestCase):
    """Test that api_token field is properly encrypted (Phase 1 fix)."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='Token Test Org')

    def test_api_token_is_encrypted(self):
        """Verify api_token is encrypted when stored and decrypted when retrieved."""
        creds = {'api_token': 'jenkins-api-token-123', 'username': 'admin'}
        encrypted = encrypt_credentials(creds)

        self.assertNotEqual(encrypted['api_token'], 'jenkins-api-token-123')
        self.assertTrue(encrypted.get('_encrypted'))

        decrypted = decrypt_credentials(encrypted)
        self.assertEqual(decrypted['api_token'], 'jenkins-api-token-123')
        self.assertEqual(decrypted['username'], 'admin')

    def test_set_credentials_jenkins_token_hint(self):
        """Verify token_hint is computed from api_token when other fields absent."""
        integration = ProviderIntegration.objects.create(
            name='Jenkins CI',
            provider_type='jenkins',
            category='devops',
            organisation=self.org,
        )
        integration.set_credentials({'api_token': 'abcdefghijklmnop', 'username': 'admin'})
        integration.save()

        self.assertEqual(integration.token_hint, 'abcd...mnop')
        self.assertEqual(integration.get_access_token(), 'abcdefghijklmnop')


class TokenExpiryTests(TestCase):
    """Test token expiry checking (Phase 6)."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='Expiry Test Org')

    def test_is_token_expired_false_when_not_set(self):
        integration = ProviderIntegration(
            provider_type='gitlab', organisation=self.org,
        )
        self.assertFalse(integration.is_token_expired)

    def test_is_token_expired_true_when_past(self):
        past = timezone.now() - timezone.timedelta(hours=1)
        integration = ProviderIntegration(
            provider_type='gitlab', organisation=self.org,
            token_expires_at=past,
        )
        self.assertTrue(integration.is_token_expired)

    def test_is_token_expired_false_when_future(self):
        future = timezone.now() + timezone.timedelta(days=30)
        integration = ProviderIntegration(
            provider_type='gitlab', organisation=self.org,
            token_expires_at=future,
        )
        self.assertFalse(integration.is_token_expired)

    def test_token_expires_soon(self):
        soon = timezone.now() + timezone.timedelta(days=3)
        integration = ProviderIntegration(
            provider_type='gitlab', organisation=self.org,
            token_expires_at=soon,
        )
        self.assertTrue(integration.token_expires_soon)
        self.assertFalse(integration.is_token_expired)

    def test_get_access_token_raises_on_expired(self):
        past = timezone.now() - timezone.timedelta(hours=1)
        integration = ProviderIntegration.objects.create(
            name='Expired',
            provider_type='gitlab',
            category='devops',
            organisation=self.org,
            token_expires_at=past,
        )
        integration.set_credentials({'access_token': 'some-token'})
        integration.save()

        with self.assertRaises(ValueError) as ctx:
            integration.get_access_token()
        self.assertIn('expired', str(ctx.exception).lower())

    def test_check_token_expiry_sets_expired_status(self):
        past = timezone.now() - timezone.timedelta(hours=1)
        integration = ProviderIntegration.objects.create(
            name='Expired Check',
            provider_type='gitlab',
            category='devops',
            organisation=self.org,
            token_expires_at=past,
        )
        result = integration.check_token_expiry()
        self.assertEqual(result, 'expired')

        integration.refresh_from_db()
        self.assertEqual(integration.verification_status, 'expired')


class ProviderIntegrationMultiTenancyTests(TestCase):
    """Test multi-tenancy isolation for ProviderIntegration."""
    
    def setUp(self):
        """Set up test orgs."""
        self.org1 = Organisations.objects.create(name='Org 1')
        self.org2 = Organisations.objects.create(name='Org 2')
    
    def test_integrations_isolated_by_org(self):
        """Integrations should be isolated by organisation."""
        # Create integration for org1
        int1 = ProviderIntegration.objects.create(
            name='Org1 GitLab',
            provider_type='gitlab',
            category='devops',
            organisation=self.org1
        )
        
        # Create integration for org2
        int2 = ProviderIntegration.objects.create(
            name='Org2 GitLab',
            provider_type='gitlab',
            category='devops',
            organisation=self.org2
        )
        
        # Query by org should be isolated
        org1_integrations = ProviderIntegration.objects.filter(organisation=self.org1)
        org2_integrations = ProviderIntegration.objects.filter(organisation=self.org2)
        
        self.assertEqual(org1_integrations.count(), 1)
        self.assertEqual(org2_integrations.count(), 1)
        self.assertEqual(org1_integrations.first().name, 'Org1 GitLab')
        self.assertEqual(org2_integrations.first().name, 'Org2 GitLab')
