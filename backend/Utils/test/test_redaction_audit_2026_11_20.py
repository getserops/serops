"""Masking, audit 2026-11-20 item 7: more token formats, linear time, a line cap.

Fixtures that look like secrets are built by concatenation so secret
scanners and push protection do not trip on this file.
"""
import time

from django.test import SimpleTestCase

from Utils.data_redaction import DataRedactionService

HEX32 = '0123456789abcdef' * 2
HEX64 = HEX32 * 2
B64ISH = 'Zx9' + 'Qm2' + 'Lr7' + 'Tp4' + 'Wy8' + 'Kc1' + 'Hv5' + 'Nd3' + 'Bf6' + 'Gs0' + 'Aj'


def redact(text):
    return DataRedactionService().redact(text)[0]


class NewFormatsTest(SimpleTestCase):
    CASES = [
        # (pattern, text, secret part that must disappear, context that must stay)
        ('stripe_key', 'charge failed key=' + 'sk_' + 'live_' + 'a1B2c3D4e5F6g7H8i9J0', 'a1B2c3D4e5F6g7H8i9J0', 'charge failed'),
        ('stripe_key', 'using ' + 'rk_' + 'live_' + 'Z9y8X7w6V5u4T3s2R1q0', 'Z9y8X7w6V5u4T3s2R1q0', 'using'),
        ('github_fine_grained_token', 'clone with ' + 'github_' + 'pat_' + '11ABCDEFG0' + 'x' * 30, 'x' * 30, 'clone with'),
        ('slack_webhook', 'POST https://hooks.slack.com/services/' + 'T000/B000/' + 'XXXXabcd1234', 'XXXXabcd1234', 'POST'),
        ('slack_app_token', 'socket mode ' + 'xapp-' + '1-A0B1C2D3E4-' + '123456789', '123456789', 'socket mode'),
        ('sendgrid_key', 'mail via ' + 'SG.' + 'abcdefghijklmnopqrstuv' + '.' + 'w' * 43, 'w' * 43, 'mail via'),
        ('twilio_key', 'twilio key ' + 'SK' + HEX32 + ' rejected', HEX32, 'rejected'),
        ('npm_token', '//registry.npmjs.org/:_authToken=' + 'npm_' + 'a' * 36, 'a' * 36, 'registry.npmjs.org'),
        ('pypi_token', 'twine upload -p ' + 'pypi-' + 'AgEIcHlwaS5vcmc' + 'b' * 50, 'b' * 50, 'twine upload'),
        ('huggingface_token', 'HF_TOKEN set to ' + 'hf_' + 'c' * 34, 'c' * 34, 'HF_TOKEN'),
        ('digitalocean_token', 'doctl using ' + 'dop_' + 'v1_' + HEX64, HEX64, 'doctl using'),
        ('google_oauth_token', 'got ' + 'ya29.' + 'a0AfH6SMB' + 'd' * 40, 'd' * 40, 'got'),
        ('azure_account_key', 'DefaultEndpointsProtocol=https;AccountName=acme;AccountKey=' + B64ISH + '==;EndpointSuffix=core',
         B64ISH, 'AccountName=acme'),
        ('azure_sas_signature', 'GET https://acme.blob.core.windows.net/c/f?sv=2022&sig=' + 'abcDEF123' + '%2Bxyz789QWE' + '&se=2026',
         'abcDEF123', 'sv=2022'),
        ('url_query_secret', 'GET /callback?code=1&access_token=' + 'tok' + 'en12345678' + '&state=x', 'token12345678', 'state=x'),
        ('url_query_secret', 'https://maps.example.com/api?key=' + 'AbCdEf' + '123456' + '&q=x', 'AbCdEf123456', 'q=x'),
        ('cookie_header', 'Cookie: session=' + 'abc' + '123' + '; theme=dark', 'session=abc123', 'Cookie:'),
        ('cookie_header', 'Set-Cookie: sid=' + 'zz' + '99' + '; Path=/; HttpOnly', 'sid=zz99', 'Set-Cookie:'),
        ('curl_user_password', 'curl -u deploy:' + 'Hunt' + 'er22' + ' https://ci.example.com', 'Hunter22', 'curl -u deploy:'),
        ('mysql_password_flag', 'mysql -h db -u root -p' + 'S3cr' + 'et99' + ' shop', 'S3cret99', 'mysql -h db -u root'),
        ('unlabelled_secret', 'signing key ' + HEX64 + ' loaded', HEX64, 'loaded'),
        ('unlabelled_secret', 'webhook secret is ' + B64ISH + 'x', B64ISH, 'webhook'),
        ('unlabelled_secret', 'loaded HMAC ' + HEX64, HEX64, 'loaded'),
        ('unlabelled_secret', 'rotating the encryption key to ' + B64ISH + 'q', B64ISH, 'rotating'),
    ]

    def test_each_format_is_masked_and_context_kept(self):
        for name, text, secret, context in self.CASES:
            with self.subTest(pattern=name, text=text[:40]):
                out = redact(text)
                self.assertNotIn(secret, out)
                self.assertIn(context, out)
                found = {f.pattern_type for f in DataRedactionService().scan(text)}
                self.assertIn(name, found)

    def test_near_misses_stay_readable(self):
        for text in (
            'sk_test_' + 'a' * 20 + ' in staging',      # Stripe test keys are out of scope
            'the npm_config_cache dir',
            'GET /items?page=2&sort=asc',
            'mysql -h db -u root -p shop',             # -p alone prompts; nothing to mask
            'key rotation scheduled for tomorrow',
            'signature check passed in 12ms',
            'cookie banner shown',
            # Identifiers called "key" (owner review, 20 Nov): never masked.
            'DETAIL:  Key (order_id)=(' + HEX32 + ') already exists.',
            'redis GET key session:' + HEX32 + ' returned nil',
            'kafka produce topic=orders partition=3 message key ' + HEX32,
            'Idempotency-Key: ' + HEX32 + ' replayed, returning the stored response',
            'idempotency key ' + HEX32 + ' seen twice',
            'cache key ' + HEX64 + ' evicted',
            'S3 object key uploads/2026/11/' + HEX32 + '.json not found',
        ):
            with self.subTest(text=text):
                self.assertEqual(redact(text), text)


class LinearTimeTest(SimpleTestCase):
    """Each of these took 2.7 to 4.6 s (the email pattern was quadratic)."""

    INPUTS = {
        'password': 'password ' + 'a' * 50000,
        'url': 'http://' + 'a' * 50000,
        'at-sign': 'a' * 40000 + '@',
        'export': 'export ' + 'A' * 50000,
        # Found while fixing: 17 to 31 s before.
        'iban-spaces': 'iban ' + ' ' * 50000,
        'ssn-spaces': 'ssn ' + ' ' * 50000,
        'api-key-spaces': 'api_key ' + ' ' * 50000,
        'dotted-run': 'token ' + 'a.b' * 16000,
    }

    def test_each_input_well_under_200_ms(self):
        service = DataRedactionService()
        for label, text in self.INPUTS.items():
            with self.subTest(input=label):
                start = time.perf_counter()
                service.redact(text)
                self.assertLess(time.perf_counter() - start, 0.2)

    def test_email_still_found(self):
        self.assertEqual(redact('mail to first.last+tag@mail.example.co.uk failed'), 'mail to [EMAIL] failed')


class LineCapTest(SimpleTestCase):
    def test_long_line_is_cut_with_a_marker(self):
        cap = DataRedactionService.MAX_LINE_CHARS
        out = redact('x' * (cap + 500))
        self.assertTrue(out.startswith('x' * cap))
        self.assertIn('[500 characters cut before redaction]', out)

    def test_short_lines_and_multiline_keys_untouched(self):
        text = '\n'.join(['ok line'] * 5000)
        self.assertEqual(redact(text), text)
        # The marker is put together here so that no secret scanner takes this
        # made-up block for a key (the GitHub sync gate did, 21 Nov).
        begin, end = '-----BEGIN RSA ' + 'PRIVATE KEY-----', '-----END RSA ' + 'PRIVATE KEY-----'
        pem = begin + '\n' + 'MIIE' + 'a' * 60 + '\n' + end
        self.assertEqual(redact('before\n' + pem + '\nafter'), 'before\n[PRIVATE_KEY]\nafter')

    def test_a_secret_after_the_cap_never_survives(self):
        cap = DataRedactionService.MAX_LINE_CHARS
        secret = 'Hunt' + 'er2299'
        out = redact('y' * cap + ' password=' + secret)
        self.assertNotIn(secret, out)
