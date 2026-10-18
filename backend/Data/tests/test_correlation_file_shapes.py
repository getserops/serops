"""
Correlations survive the real shape of a commit's file list.

CodeChange.to_ai_summary() lists files as {'path', 'diff'} dicts. The
file-to-error matcher called ``.endswith`` on them, raised, and
ai_model.tasks caught the error and dropped *every* correlation for the
batch (metric, span and CI/CD ones too) whenever an error log named a file.
"""
from django.test import SimpleTestCase

from Data.correlation_engine import build_comprehensive_correlations, correlate_logs_with_code_changes

LOGS = [{
    'message': 'Traceback: File "/app/api/payment_webhooks.py", line 42, in handle',
    'timestamp': '2026-10-18T10:05:00Z',
}]


def _change(files):
    return {'sha': 'abc12345ff', 'message': 'retry webhooks', 'timestamp': '2026-10-18T10:00:00Z', 'files': files}


class FileShapeTests(SimpleTestCase):
    def test_dict_files_match_by_path(self):
        out = correlate_logs_with_code_changes(LOGS, [_change([{'path': 'api/payment_webhooks.py', 'diff': '@@ ...'}])])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['commit_sha'], 'abc12345')

    def test_string_files_still_match(self):
        out = correlate_logs_with_code_changes(LOGS, [_change(['api/payment_webhooks.py'])])
        self.assertEqual(len(out), 1)

    def test_whole_correlation_build_does_not_raise(self):
        result = build_comprehensive_correlations(
            logs=LOGS, metrics_summary={}, code_changes=[_change([{'path': 'api/payment_webhooks.py', 'diff': ''}])],
        )
        self.assertEqual(len(result['correlations']['file_to_error']), 1)

    def test_correlation_output_lists_paths_not_diffs(self):
        # files_changed is persisted on batch.data; diffs there would bloat it.
        from Data.correlation_engine import _file_path
        self.assertEqual(_file_path({'path': 'a.py', 'diff': 'x' * 10_000}), 'a.py')
        self.assertEqual(_file_path('b.py'), 'b.py')
        self.assertEqual(_file_path(None), '')
