"""
Tests for Data Redaction Service

Written originally in pytest style (plain classes, ``setup_method``), which
Django's test runner does not collect — combined with ``Utils/`` lacking
package ``__init__`` files, none of these ran. SimpleTestCase: no database.
"""

from django.test import SimpleTestCase

from Utils.data_redaction import (
    DataRedactionService, 
    SensitivityLevel, 
    RedactedItem,
    redact_batch_logs,
    redact_code_changes
)


class TestDataRedactionService(SimpleTestCase):
    """Tests for the DataRedactionService class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.service = DataRedactionService()
    
    # ==========================================
    # CREDENTIAL DETECTION TESTS
    # ==========================================
    
    def test_detects_password_in_log(self):
        """Should detect password patterns."""
        text = "Connection failed: password=SecretPass123"
        findings = self.service.scan(text)
        
        assert len(findings) >= 1
        assert any(f.pattern_type == 'password' for f in findings)
        assert any(f.sensitivity == SensitivityLevel.CRITICAL for f in findings)
    
    def test_detects_password_variations(self):
        """Should detect various password formats."""
        test_cases = [
            'password=mypass123',
            'PASSWORD: "mypass123"',
            "pwd='mypass123'",
            'secret=mypass123',
            'credential: mypass123',
        ]
        
        for text in test_cases:
            findings = self.service.scan(text)
            assert len(findings) >= 1, f"Failed to detect password in: {text}"
    
    def test_detects_api_key(self):
        """Should detect API key patterns."""
        text = "api_key=sk_live_1234567890abcdefghij"
        findings = self.service.scan(text)
        
        assert len(findings) >= 1
        assert any(f.pattern_type == 'api_key' for f in findings)
    
    def test_detects_aws_access_key(self):
        """Should detect AWS access key pattern."""
        text = "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
        findings = self.service.scan(text)
        
        assert len(findings) >= 1
        assert any(f.pattern_type == 'aws_access_key' for f in findings)
    
    def test_detects_jwt_token(self):
        """Should detect JWT token pattern."""
        text = "token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        findings = self.service.scan(text)
        
        assert len(findings) >= 1
        assert any(f.pattern_type == 'jwt_token' for f in findings)
    
    def test_detects_bearer_token(self):
        """Should detect Bearer token pattern."""
        text = "Authorization: Bearer abcdef1234567890abcdefghijklmnop"
        findings = self.service.scan(text)
        
        assert len(findings) >= 1
        assert any(f.pattern_type == 'bearer_token' for f in findings)
    
    def test_detects_private_key(self):
        """Should detect private key patterns."""
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIBOg..."
        findings = self.service.scan(text)
        
        assert len(findings) >= 1
        assert any(f.pattern_type == 'private_key' for f in findings)
    
    def test_detects_gitlab_token(self):
        """Should detect GitLab personal access token."""
        text = "GITLAB_TOKEN=glpat-abcdefghijklmnopqrstuvwxyz"
        findings = self.service.scan(text)
        
        assert len(findings) >= 1
        assert any(f.pattern_type == 'gitlab_token' for f in findings)
    
    def test_detects_github_token(self):
        """Should detect GitHub token patterns."""
        test_cases = [
            "GITHUB_TOKEN=ghp_1234567890abcdefghijklmnopqrstuvwxyz",
            "github_token=gho_1234567890abcdefghijklmnopqrstuvwxyz",
        ]
        
        for text in test_cases:
            findings = self.service.scan(text)
            assert len(findings) >= 1, f"Failed to detect GitHub token in: {text}"
    
    # ==========================================
    # PII DETECTION TESTS
    # ==========================================
    
    def test_detects_email(self):
        """Should detect email addresses."""
        text = "Contact: john.doe@example.com for support"
        findings = self.service.scan(text)
        
        assert len(findings) >= 1
        assert any(f.pattern_type == 'email' for f in findings)
        assert any(f.sensitivity == SensitivityLevel.HIGH for f in findings)
    
    def test_detects_phone_us(self):
        """Should detect US phone numbers."""
        test_cases = [
            "Call us at 555-123-4567",
            "Phone: (555) 123-4567",
            "Tel: 1-555-123-4567",
        ]
        
        for text in test_cases:
            findings = self.service.scan(text)
            assert len(findings) >= 1, f"Failed to detect phone in: {text}"
    
    def test_detects_ssn(self):
        """Should detect social security numbers."""
        text = "SSN: 123-45-6789"
        findings = self.service.scan(text)
        
        assert len(findings) >= 1
        assert any(f.pattern_type == 'ssn' for f in findings)
    
    def test_detects_credit_card(self):
        """Should detect credit card numbers."""
        test_cases = [
            "Card: 4111111111111111",  # Visa
            "Card: 5500000000000004",  # Mastercard
            "Card: 4111-1111-1111-1111",  # Formatted
        ]
        
        for text in test_cases:
            findings = self.service.scan(text)
            assert len(findings) >= 1, f"Failed to detect credit card in: {text}"
    
    # ==========================================
    # INFRASTRUCTURE DETECTION TESTS
    # ==========================================
    
    def test_detects_connection_string(self):
        """Should detect database connection strings."""
        test_cases = [
            "DATABASE_URL=postgresql://user:pass@localhost:5432/db",
            "MONGO_URL=mongodb://user:pass@cluster.mongodb.net/db",
            "REDIS_URL=redis://localhost:6379",
        ]
        
        for text in test_cases:
            findings = self.service.scan(text)
            assert len(findings) >= 1, f"Failed to detect connection string in: {text}"
    
    def test_detects_private_ip(self):
        """Should detect private IP addresses."""
        test_cases = [
            "Server: 192.168.1.100",
            "Host: 10.0.0.1",
            "IP: 172.16.0.1",
        ]
        
        for text in test_cases:
            findings = self.service.scan(text)
            assert len(findings) >= 1, f"Failed to detect private IP in: {text}"
    
    def test_detects_s3_bucket(self):
        """Should detect S3 bucket URLs."""
        text = "Upload to s3://my-secret-bucket/path/to/file"
        findings = self.service.scan(text)
        
        assert len(findings) >= 1
        assert any(f.pattern_type == 's3_bucket' for f in findings)
    
    # ==========================================
    # REDACTION TESTS
    # ==========================================
    
    def test_redact_password(self):
        """Should redact password with mask."""
        text = "password=MySecretPass123"
        redacted, findings = self.service.redact(text)
        
        assert "MySecretPass123" not in redacted
        assert "*****" in redacted or "[" in redacted
    
    def test_redact_multiple_findings(self):
        """Should redact multiple sensitive items."""
        text = "email: user@test.com, password=secret123"
        redacted, findings = self.service.redact(text)
        
        assert "user@test.com" not in redacted
        assert "secret123" not in redacted
        assert len(findings) >= 2
    
    def test_redact_preserves_non_sensitive(self):
        """Should preserve non-sensitive text."""
        text = "Normal log message without secrets"
        redacted, findings = self.service.redact(text)
        
        assert redacted == text
        assert len(findings) == 0
    
    # ==========================================
    # BATCH PROCESSING TESTS
    # ==========================================
    
    def test_redact_batch_logs(self):
        """Should redact a batch of logs."""
        logs = [
            {'_source': {'message': 'password=secret'}},
            {'_source': {'message': 'Normal log'}},
            {'_source': {'message': 'api_key=abcdef1234567890abcdef'}},
        ]
        
        redacted_logs, summary = redact_batch_logs(logs)
        
        assert len(redacted_logs) == 3
        assert summary['total_count'] >= 2
        assert redacted_logs[0]['_source']['_redaction_applied'] == True
        assert redacted_logs[1]['_source']['_redaction_applied'] == False
    
    def test_redact_code_changes(self):
        """Should redact code change diffs."""
        changes = [
            {'diff': '+password = "secret123"', 'message': 'Add config'},
            {'diff': '+import os', 'message': 'Update imports'},
        ]
        
        redacted_changes, summary = redact_code_changes(changes)
        
        assert len(redacted_changes) == 2
        assert "secret123" not in redacted_changes[0]['diff']
    
    # ==========================================
    # CONFIGURATION TESTS
    # ==========================================
    
    def test_custom_patterns(self):
        """Should support custom patterns."""
        config = {
            'custom_patterns': {
                'company_id': (r'COMP-\d{6}', SensitivityLevel.HIGH)
            }
        }
        service = DataRedactionService(config)
        
        text = "Employee ID: COMP-123456"
        findings = service.scan(text)
        
        assert any(f.pattern_type == 'company_id' for f in findings)
    
    def test_disabled_patterns(self):
        """Should respect disabled patterns."""
        config = {
            'patterns': ['password']  # Only enable password
        }
        service = DataRedactionService(config)
        
        text = "email: user@test.com, password=secret"
        findings = service.scan(text)
        
        # Should only find password, not email
        assert len(findings) >= 1
        assert all(f.pattern_type == 'password' for f in findings)
    
    # ==========================================
    # EDGE CASE TESTS
    # ==========================================
    
    def test_empty_text(self):
        """Should handle empty text."""
        findings = self.service.scan("")
        redacted, _ = self.service.redact("")
        
        assert findings == []
        assert redacted == ""
    
    def test_none_text(self):
        """Should handle None gracefully."""
        findings = self.service.scan(None)
        redacted, _ = self.service.redact(None)
        
        assert findings == []
        assert redacted is None
    
    def test_summary_generation(self):
        """Should generate proper summary."""
        text = "password=test email=user@test.com api_key=abcdef1234567890abcdef"
        findings = self.service.scan(text)
        summary = self.service.get_summary(findings)
        
        assert 'total_count' in summary
        assert 'by_severity' in summary
        assert 'by_type' in summary
        assert summary['total_count'] >= 2


class TestRedactedItem(SimpleTestCase):
    """Tests for RedactedItem dataclass."""
    
    def test_to_dict(self):
        """Should convert to dictionary."""
        item = RedactedItem(
            pattern_type='password',
            original_length=10,
            position=(5, 15),
            sensitivity=SensitivityLevel.CRITICAL,
            context='...***...'
        )
        
        d = item.to_dict()
        
        assert d['pattern_type'] == 'password'
        assert d['sensitivity'] == 'critical'
        assert d['position'] == [5, 15]


class TestOverlappingMatchesNeverLeak(SimpleTestCase):
    """Overlapping matches must be masked as their union.

    `_deduplicate_findings` used to keep one of two overlapping matches and
    discard the other, masking only the kept span. For ``token=<JWT>`` the
    generic ``token=`` pattern stops at the JWT's first dot and won the tie,
    so the redacted text read ``[SECRET].<payload>.<signature>`` — and with
    the header a well-known constant, that is the whole token, sent to the AI
    provider. These assert on what *survives*, not on which label won.
    """

    JWT = ('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9'
           '.eyJzdWIiOiIxMjM0NTY3ODkwIn0'
           '.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U')

    def setUp(self):
        self.service = DataRedactionService()

    def assert_no_fragment_survives(self, secret, redacted):
        for part in secret.replace('-', '.').split('.'):
            if len(part) >= 6:
                self.assertNotIn(part, redacted)

    def test_jwt_after_a_token_key(self):
        redacted, _ = self.service.redact(f'token={self.JWT}')
        self.assert_no_fragment_survives(self.JWT, redacted)

    def test_jwt_after_an_auth_key_in_json(self):
        redacted, _ = self.service.redact(f'{{"auth_token": "{self.JWT}"}}')
        self.assert_no_fragment_survives(self.JWT, redacted)

    def test_gitlab_token_after_a_key(self):
        secret = 'glpat-abcdefghijklmnopqrstuvwxyz'
        redacted, _ = self.service.redact(f'GITLAB_TOKEN={secret}')
        self.assertNotIn('abcdefghijklmnopqrstuvwxyz', redacted)

    def test_merged_finding_spans_the_union(self):
        text = f'token={self.JWT}'
        findings = self.service.scan(text)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].position, (0, len(text)))

    def test_separate_secrets_stay_separate(self):
        findings = self.service.scan(
            'password=hunter2xyz and contact admin@example.com')
        self.assertGreaterEqual(len(findings), 2)


class TestCustomPatternsAreScopedToTheirInstance(SimpleTestCase):
    """Custom patterns used to be written into the class-level PATTERNS dict:
    never scanned for the caller who asked (added after the enabled list was
    built), and leaked into every later instance in the process."""

    def test_custom_pattern_does_not_leak_to_other_instances(self):
        DataRedactionService({'custom_patterns': {
            'leaky_id': (r'LEAK-\d{4}', SensitivityLevel.HIGH)}})
        self.assertNotIn('leaky_id', DataRedactionService.PATTERNS)
        findings = DataRedactionService().scan('ref LEAK-1234')
        self.assertFalse(any(f.pattern_type == 'leaky_id' for f in findings))

    def test_custom_pattern_honoured_alongside_a_restricted_list(self):
        service = DataRedactionService({
            'patterns': ['password'],
            'custom_patterns': {'company_id': (r'COMP-\d{6}', SensitivityLevel.HIGH)},
        })
        types = {f.pattern_type for f in service.scan('COMP-123456 password=abcdefgh1')}
        self.assertEqual(types, {'company_id', 'password'})
