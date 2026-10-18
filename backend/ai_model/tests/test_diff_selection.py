"""
The AI reads the part of a diff that the incident points at.

Before: the first 500 characters of each changed file. A bug further down
a diff was invisible, and every file got the same space whether or not a
stack frame named it.
"""
from django.test import SimpleTestCase

from ai_model.diff_selection import (
    StackRef,
    build_code_changes_section,
    error_tokens,
    extract_stack_refs,
)


def _hunk(start, body_lines, context=''):
    return f'@@ -{start},{len(body_lines)} +{start},{len(body_lines)} @@ {context}\n' + '\n'.join(body_lines)


# A 3-hunk diff where only the third hunk (lines 140-150) is the bug.
FILLER = [f' unchanged_line_{i} = {i}' for i in range(40)]
PAYMENTS_DIFF = '\n'.join([
    _hunk(1, ['-import os', '+import os, sys'] + FILLER[:10], 'imports'),
    _hunk(60, [' def format_amount(x):', '-    return str(x)', '+    return f"{x:.2f}"'] + FILLER[:30], 'def format_amount'),
    _hunk(140, [
        ' def charge(order):',
        '-    timeout = 30',
        '+    timeout = 5',
        '     return gateway.post(order, timeout=timeout)',
    ], 'def charge'),
])

PY_TRACE = [
    'ERROR payment-worker Traceback (most recent call last):',
    '  File "/usr/local/lib/python3.12/site-packages/requests/api.py", line 59, in request',
    '  File "/app/api/payments.py", line 143, in charge',
    'requests.exceptions.ReadTimeout: HTTPSConnectionPool read timeout=5',
]


class ExtractStackRefsTests(SimpleTestCase):
    def test_python_frames_skip_libraries(self):
        refs = extract_stack_refs(PY_TRACE)
        self.assertIn(StackRef('/app/api/payments.py', 143, 'charge'), refs)
        self.assertFalse(any('site-packages' in r.path for r in refs))

    def test_java_javascript_go_ruby_php_csharp(self):
        refs = extract_stack_refs([
            'at com.acme.pay.Retry.run(Retry.java:42)',
            'at handle (/app/src/pay/checkout.ts:12:5)',
            'goroutine 1 [running]:\n/app/internal/pay/retry.go:88 +0x1d',
            "app/models/order.rb:17:in `charge'",
            '#0 /var/www/src/Pay.php(31): Pay->run()',
            'at Acme.Pay.Retry.Run() in /src/Pay/Retry.cs:line 9',
        ])
        found = {(posix.split('/')[-1], line) for posix, line in ((r.path, r.line) for r in refs)}
        for expected in [('Retry.java', 42), ('checkout.ts', 12), ('retry.go', 88), ('order.rb', 17), ('Pay.php', 31), ('Retry.cs', 9)]:
            self.assertIn(expected, found)

    def test_ignores_logs_without_frames(self):
        self.assertEqual(extract_stack_refs(['GET /health 200 3ms', '', None]), [])


class ErrorTokensTests(SimpleTestCase):
    def test_keeps_distinctive_identifiers_from_error_lines_only(self):
        tokens = error_tokens(['INFO started worker pool', 'ERROR ConnectionRefusedError connecting to redis_cache'])
        self.assertIn('connectionrefusederror', tokens)
        self.assertIn('redis_cache', tokens)
        self.assertNotIn('started', tokens)
        self.assertNotIn('error', tokens)


class BuildCodeChangesSectionTests(SimpleTestCase):
    def _change(self, files, sha='e7d3b201aa'):
        return {'sha': sha, 'author': 'Priya', 'timestamp': '2026-10-18T10:00:00Z', 'branch': 'main',
                'message': 'tune payment timeout', 'stats': {'files': len(files), 'additions': 3, 'deletions': 2},
                'files': files}

    def test_the_hunk_the_stack_trace_names_is_shown_even_far_down_the_diff(self):
        section = build_code_changes_section(
            [self._change([{'path': 'api/payments.py', 'diff': PAYMENTS_DIFF}])], PY_TRACE)
        self.assertIn('+    timeout = 5', section)
        self.assertIn('[in stack trace: line 143, in charge]', section)
        # The unrelated hunks of a file the trace names are left out.
        self.assertNotIn('format_amount', section)
        self.assertIn('(1 of 3 hunks)', section)

    def test_old_behaviour_would_have_missed_it(self):
        # Guard on the fixture itself: the bug is past the old 500-char cut.
        self.assertNotIn('timeout = 5', PAYMENTS_DIFF[:500])

    def test_files_the_logs_point_at_get_the_budget_first(self):
        big_unrelated = _hunk(1, [f'+ css_rule_{i} {{ color: red }}' for i in range(400)], 'styles')
        section = build_code_changes_section(
            [
                self._change([{'path': 'web/styles.css', 'diff': big_unrelated}], sha='aaaaaaaa1'),
                self._change([{'path': 'api/payments.py', 'diff': PAYMENTS_DIFF}], sha='bbbbbbbb2'),
            ],
            PY_TRACE,
            total_budget=2_000,
        )
        self.assertIn('+    timeout = 5', section)
        self.assertLess(section.count('css_rule_'), 40)

    def test_without_logs_every_file_still_gets_a_short_excerpt(self):
        section = build_code_changes_section(
            [self._change([{'path': 'api/payments.py', 'diff': PAYMENTS_DIFF}])], [])
        self.assertIn('File: api/payments.py', section)
        self.assertIn('@@ -1,12 +1,12 @@ imports', section)
        self.assertNotIn('in stack trace', section)

    def test_legacy_string_files_and_missing_diffs(self):
        section = build_code_changes_section([self._change(['api/payments.py', {'path': 'README.md'}])], PY_TRACE)
        self.assertIn('File: api/payments.py  [in stack trace', section)
        self.assertIn('File: README.md', section)

    def test_section_stays_inside_the_budget(self):
        huge = _hunk(1, [f'+ line_{i} = "{"x" * 60}"' for i in range(2000)])
        changes = [self._change([{'path': f'svc/mod_{i}.py', 'diff': huge} for i in range(8)], sha=f'{i:08d}') for i in range(10)]
        section = build_code_changes_section(changes, PY_TRACE, total_budget=12_000)
        self.assertLess(len(section), 12_000 + 6_000)  # budget + headers and file lists

    def test_empty(self):
        self.assertEqual(build_code_changes_section([], PY_TRACE), '')
        self.assertEqual(build_code_changes_section(None, None), '')


class RedactionTests(SimpleTestCase):
    """Diffs carry secrets as often as logs do (a hardcoded key is a
    one-line commit). They are masked before the prompt, like logs."""

    SECRET_DIFF = '@@ -1,2 +1,2 @@\n-API_KEY = os.environ["API_KEY"]\n+API_KEY = "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"\n contact = "ops@acme.example.com"'

    def _change(self, diff, message='rotate key'):
        return {'sha': 'abc12345', 'author': 'dev', 'timestamp': 't', 'branch': 'main', 'message': message,
                'files': [{'path': 'settings.py', 'diff': diff}]}

    def test_secrets_and_emails_in_diffs_are_masked(self):
        section = build_code_changes_section([self._change(self.SECRET_DIFF)], [])
        self.assertNotIn('sk-ant-api03-AbCdEfGhIjKl', section)
        self.assertNotIn('ops@acme.example.com', section)
        self.assertIn('settings.py', section)
        self.assertIn('API_KEY', section)  # the shape of the change stays readable

    def test_commit_messages_are_masked(self):
        section = build_code_changes_section(
            [self._change('@@ -1 +1 @@\n-a\n+b', message='hotfix for alice@acme.example.com')], [])
        self.assertNotIn('alice@acme.example.com', section)

    def test_fails_closed_when_redaction_breaks(self):
        def broken(_text):
            raise RuntimeError('pattern compile error')
        section = build_code_changes_section([self._change(self.SECRET_DIFF)], [], redact=broken)
        self.assertNotIn('sk-ant-api03', section)
        self.assertIn('Diff: withheld (redaction unavailable)', section)
        self.assertIn('File: settings.py', section)
