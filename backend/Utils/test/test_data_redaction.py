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
    
    def test_trace_ids_are_not_phone_numbers(self):
        """Ten digits inside a hex trace ID used to become [PHONE]
        (trace_id=41cce[PHONE]d0c237...), breaking log-to-trace links."""
        for text in [
            "trace_id=41cce4155550123d0c2378a9b1e2f3c4 span_id=00f067aa0ba902b7",
            "span 9a1234567890ff took 1200ms",
            "request +1234567x retried",
        ]:
            findings = self.service.scan(text)
            assert not any(f.pattern_type.startswith('phone') for f in findings), text

    def test_phone_next_to_punctuation_is_still_found(self):
        for text in ["phone=555-123-4567;", "call +442071838750.", "(555) 123-4567"]:
            findings = self.service.scan(text)
            assert any(f.pattern_type.startswith('phone') for f in findings), text

    def test_bare_numbers_are_not_phones_or_ssns(self):
        """Byte counts, timestamps, counters and diff hunks stay readable:
        the whole prompt is redacted, and an OOM analysis needs the limit."""
        for text in [
            "memory working set 1073741824 bytes, limit 1610612736 bytes",
            "iat=1792332094, now=1792332000",
            "container_cpu_cfs_throttled_seconds_total 123456789",
            "deployed by pipeline 1234567890",
            "@@ -54,11 +54,15 @@ class StockService:",
            "build 20261104.3, 3001ms, 1840 spans",
        ]:
            redacted, _ = self.service.redact(text)
            assert '[PHONE]' not in redacted and '[SSN]' not in redacted, (text, redacted)

    def test_an_unset_database_url_message_stays_readable(self):
        redacted, _ = self.service.redact("Error: DATABASE_URL is not set")
        assert redacted == "Error: DATABASE_URL is not set"
        redacted, _ = self.service.redact("DATABASE_URL=postgres://u:pw@db/x")
        assert 'pw' not in redacted

    def test_labeled_phone_and_ssn_without_formatting_are_found(self):
        for text, kind in [("phone=5551234567", 'phone'), ('"mobile": "+33612345678"', 'phone'),
                           ("tel: 0612345678", 'phone'), ("ssn=123456789", 'ssn'), ("+33 6 12 34 56 78", 'phone')]:
            findings = self.service.scan(text)
            assert any(f.pattern_type.startswith(kind) for f in findings), text

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


class TestGenericSecretLeavesProseAlone(SimpleTestCase):
    """The catch-all accepted a bare space as the separator, so error text
    that merely mentioned a token or auth was blanked before the AI saw it."""

    def setUp(self):
        self.service = DataRedactionService()

    def test_error_prose_is_kept(self):
        for text in ('token rejected: issued in the future',
                     'auth service unavailable, retrying',
                     'secret manager request timed out',
                     'refresh token expired for session',
                     'password reset failed for user',
                     'credential expired, re-authenticating'):
            with self.subTest(text=text):
                redacted, _ = self.service.redact(text)
                self.assertEqual(redacted, text)

    def test_secrets_are_still_redacted(self):
        for text, secret in (('token=abcdef123456', 'abcdef123456'),
                             ('AUTH_TOKEN: "s3cr3tvalue99"', 's3cr3tvalue99'),
                             ('secret_key = x9f8e7d6c5b4', 'x9f8e7d6c5b4'),
                             ('using auth token 9a8b7c6d5e4f3a2b1c0d', '9a8b7c6d5e4f3a2b1c0d'),
                             ('password: hunter2', 'hunter2'),
                             ('login with password Winter2026!', 'Winter2026!')):
            with self.subTest(text=text):
                redacted, _ = self.service.redact(text)
                self.assertNotIn(secret, redacted)


class TestReviewFindingPatterns(SimpleTestCase):
    """External review (v1.2.13) ran the redactor directly and found these
    secrets left intact. Each must now be masked; the prose and diagnostic
    values next to them must not be."""

    PEM = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEAu1SU1LfVLPHCozMxH2Mo4lgOEePzNm0tRgeLezV6ffAt0gun\n"
        "VTLw7onLRnrq0/IzW7yWR7QkrmBL7jTKEn5u+qKhbwKfBstIs+bMY2Zkp18gnTxK\n"
        "-----END RSA PRIVATE KEY-----"
    )

    def setUp(self):
        self.service = DataRedactionService()

    def redact(self, text):
        return self.service.redact(text)[0]

    def test_docker_login_password_flag_is_masked_and_the_command_kept(self):
        out = self.redact('docker login -u ci -p S3cr3tPassw0rd registry.example.com')
        self.assertEqual(out, 'docker login -u ci -p ***** registry.example.com')

    def test_docker_login_long_password_flag_is_masked(self):
        out = self.redact('docker login --password=hunter22 reg.io')
        self.assertNotIn('hunter22', out)

    def test_docker_login_password_stdin_is_left_alone(self):
        text = 'echo $TOKEN | docker login --password-stdin -u ci reg.io'
        self.assertEqual(self.redact(text), text)

    def test_authorization_basic_header_is_masked(self):
        out = self.redact('Authorization: Basic dXNlcjpwYXNzd29yZA==')
        self.assertEqual(out, 'Authorization: Basic [REDACTED]')

    def test_other_authorization_schemes_are_masked(self):
        out = self.redact('authorization: Token 9f8e7d6c5b4a')
        self.assertNotIn('9f8e7d6c5b4a', out)

    def test_bare_basic_credentials_are_masked_but_prose_is_not(self):
        self.assertNotIn('dXNlcjpwYXNzd29yZA', self.redact('sent Basic dXNlcjpwYXNzd29yZA== upstream'))
        prose = 'Basic authentication failed for user'
        self.assertEqual(self.redact(prose), prose)

    def test_anthropic_key_is_masked_with_or_without_a_key_word(self):
        key = 'sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-abcdEFGH'
        for text in (f'key={key}', f'using {key} now', key):
            self.assertNotIn(key[10:], self.redact(text), text)

    def test_openai_keys_are_masked(self):
        for key in ('sk-proj-abcdefghijklmnopqrstuvwx1234567890',
                    'sk-abcdefghijklmnopqrstuvwxyz0123456789ABCD'):
            self.assertEqual(self.redact(key), 'sk-[REDACTED]')

    def test_a_word_ending_in_sk_is_not_a_key(self):
        text = 'task-abcdefghijklmnopqrstuvwxyz0123 finished'
        self.assertEqual(self.redact(text), text)

    def test_google_api_key_is_masked(self):
        key = 'AIzaSyA1234567890abcdefghijklmnopqrstuv'
        self.assertNotIn(key, self.redact(f'gemini key {key}'))

    def test_french_and_other_password_key_words_are_masked(self):
        for text in ('mot de passe: hunter2', 'mot de passe : hunter22', 'mdp=hunter22',
                     'Passwort: geheim123', 'contraseña=secreto1', 'senha: segredo1'):
            out = self.redact(text)
            self.assertNotIn(text.split(':')[-1].split('=')[-1].strip(), out, text)

    def test_public_ipv4_is_masked(self):
        self.assertEqual(self.redact('connect to 8.8.8.8 failed'), 'connect to [PUBLIC_IP] failed')
        self.assertEqual(self.redact('from 203.0.113.45:443.'), 'from [PUBLIC_IP]:443.')

    def test_private_ips_keep_their_own_mask(self):
        self.assertEqual(self.redact('host 10.0.0.5'), 'host [PRIVATE_IP]')
        self.assertEqual(self.redact('host 192.168.1.20'), 'host [PRIVATE_IP]')

    def test_loopback_link_local_netmask_and_versions_are_not_ips_to_hide(self):
        for text in ('connection refused 127.0.0.1:5432', 'bind 0.0.0.0:8080',
                     'metadata 169.254.169.254 timed out', 'netmask 255.255.255.0',
                     'image v1.2.3.4', 'version 1.2.3.4.5'):
            self.assertEqual(self.redact(text), text, text)

    def test_the_whole_private_key_block_is_masked_including_the_body(self):
        out = self.redact(f'loaded key\n{self.PEM}\ndone')
        self.assertEqual(out, 'loaded key\n[PRIVATE_KEY]\ndone')

    def test_a_private_key_cut_off_before_its_footer_is_masked_to_the_end(self):
        out = self.redact(self.PEM.split('-----END')[0])
        self.assertEqual(out, '[PRIVATE_KEY]')

    def test_other_private_key_flavours_are_masked(self):
        for header in ('PRIVATE KEY', 'ENCRYPTED PRIVATE KEY', 'OPENSSH PRIVATE KEY',
                       'PGP PRIVATE KEY BLOCK'):
            text = f'-----BEGIN {header}-----\nAAAAB3NzaC1yc2E\n-----END {header}-----'
            self.assertEqual(self.redact(text), '[PRIVATE_KEY]', header)

    def test_credentials_in_a_url_are_masked_and_the_scheme_and_user_kept(self):
        out = self.redact('pull via http://proxy:p4ss!w0rd@10.0.0.9:3128 failed')
        self.assertEqual(out, 'pull via http://proxy:*****@[PRIVATE_IP]:3128 failed')
        # ``password@host.tld`` also reads as an e-mail address; the merged
        # mask then covers the host too, which is more redaction, not less.
        out = self.redact('git clone https://oauth2:glpat-abcdefghij0123456789@gitlab.example.com/x.git')
        self.assertNotIn('glpat-abcdefghij0123456789', out)
        self.assertIn('git clone https://oauth2:', out)

    def test_redacting_twice_gives_the_same_text_as_redacting_once(self):
        """``generate_text_unified`` redacts text that callers may already have
        redacted; no mask may be re-mangled by a second pass."""
        text = (
            f'docker login -u ci -p S3cr3t1 r.io; Authorization: Basic dXNlcjpwYXNz; '
            f'sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz0123; mot de passe: hunter2; '
            f'8.8.8.8 10.0.0.1; https://u:p4ss@h.io; password=abc12345; '
            f'Bearer abcdefghijklmnopqrstuvwxyz; glpat-abcdefghijklmnopqrst; '
            f'AKIAIOSFODNN7EXAMPLE; a@b.io; s3://bucket/key; export FOO=bar; '
            f'postgres://u:p@db/x; token=abcdefgh1234; {self.PEM}'
        )
        once = self.redact(text)
        self.assertEqual(self.redact(once), once)

    def test_every_mask_is_stable_under_redaction(self):
        for name, mask in DataRedactionService.MASKS.items():
            self.assertEqual(self.redact(mask), mask, name)
