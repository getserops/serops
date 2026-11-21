"""Utils/secret_scan.py: literal passwords in committed configuration.

The fluentd file removed on 2026-11-20 had this shape: a `<match>` block with
`host`, `user` and `password` as bare directives. Fixtures are synthetic and
built by concatenation so scanners and push protection do not trip on them.
"""
import io
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from django.test import SimpleTestCase

from Utils.secret_scan import main, scan_text

PW = 'pass' + 'word'
VALUE = 'Qm9' + 'x7LkT' + 'r2wPz'          # literal, not base64-shaped enough on its own
B64 = 'c2Vj' + 'cmV0LXZhbHVl' + 'LTEyMzQ1Njc4OQ=='


def rules(text, path):
    return [rule for _, _, rule in scan_text(text, path)]


class LeakedFluentdShapeTest(SimpleTestCase):
    def test_bare_directive_pair_is_caught(self):
        conf = ('<match app.**>\n  @type elasticsearch\n  host es.internal.lan\n  port 9200\n'
                '  user ' + 'logwriter' + '\n  ' + PW + ' ' + VALUE + '\n</match>\n')
        self.assertEqual(scan_text(conf, 'backend/fluentd/conf/fluent.conf'),
                         [('backend/fluentd/conf/fluent.conf', 6, 'user-password-pair')])

    def test_bare_directive_without_user_is_still_caught(self):
        self.assertEqual(rules('  ' + PW + ' ' + VALUE + '\n', 'x.conf'), ['password-literal'])


class FormsTest(SimpleTestCase):
    def test_key_value_forms_in_configuration(self):
        for line in (PW + '=' + VALUE, PW + ': ' + VALUE, '"' + PW + '": "' + VALUE + '"',
                     'DB_' + PW.upper() + '=' + VALUE, 'redis_' + PW + ': "' + VALUE + '"'):
            with self.subTest(line=line):
                self.assertEqual(rules(line, 'settings.yml'), ['password-literal'])

    def test_base64_looking_password_caught_in_code_too(self):
        self.assertEqual(rules('client = Client(' + PW + '="' + B64 + '")', 'app.py'), ['encoded-password'])
        self.assertEqual(rules(PW + ' ' + B64, 'fluent.conf'), ['encoded-password'])

    def test_plain_literal_in_code_is_left_to_review(self):
        # Tests use throwaway passwords on purpose; only config files are held to this.
        self.assertEqual(rules(PW + "='" + VALUE + "'", 'test_views.py'), [])


class NotReportedTest(SimpleTestCase):
    def test_placeholders(self):
        for value in ('${DB_PASSWORD}', '${REDIS_PASSWORD:?required}', '"#{ENV[\'ES_PASS\']}"',
                      '<your-password>', '{{ .Values.pw }}', 'change-me', 'changeme', 'example',
                      'xxxxxx', '********', '""', 'u.password', 'empty'):
            with self.subTest(value=value):
                self.assertEqual(rules(PW + ': ' + value, 'a.yml'), [])
                self.assertEqual(rules('  ' + PW + ' ' + value, 'a.conf'), [])

    def test_prose_and_labels(self):
        self.assertEqual(rules('# the ' + PW + ' is required below', 'a.conf'), [])
        self.assertEqual(rules('"' + PW + '": "Password",', 'en.json'), [])

    def test_allow_marker(self):
        self.assertEqual(rules(PW.upper() + ': testpass  # secret-scan: allow (CI database)', 'ci.yml'), [])


class OutputTest(SimpleTestCase):
    def test_exit_code_and_value_never_printed(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / 'fluent.conf'
            bad.write_text('  user writer\n  ' + PW + ' ' + VALUE + '\n')
            good = Path(d) / 'ok.conf'
            good.write_text('  ' + PW + ' "#{ENV[\'ES_PASS\']}"\n')
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(main([str(bad)]), 1)
                self.assertEqual(main([str(good)]), 0)
        self.assertIn('fluent.conf:2: user-password-pair', out.getvalue())
        self.assertNotIn(VALUE, out.getvalue())
