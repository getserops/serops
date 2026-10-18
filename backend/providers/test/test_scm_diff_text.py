"""
Every SCM provider stores the diff text the AI reads, not only file names.

GitLab always did. GitHub, Bitbucket and Azure DevOps stored paths and
line counts, so for those users the prompt had no changed line to read.
"""
import unittest
from unittest.mock import MagicMock, patch

from providers.scm_providers import (
    AzureDevOpsProvider,
    BitbucketProvider,
    GitHubProvider,
    split_unified_diff,
    unified_diff_text,
)

RAW_DIFF = """diff --git a/api/pay.py b/api/pay.py
index 1111111..2222222 100644
--- a/api/pay.py
+++ b/api/pay.py
@@ -10,3 +10,3 @@ def charge(order):
-    timeout = 30
+    timeout = 5
     return post(order)
diff --git a/docs/old.md b/docs/new.md
similarity index 90%
rename from docs/old.md
rename to docs/new.md
--- a/docs/old.md
+++ b/docs/new.md
@@ -1 +1 @@
-Old title
+New title
diff --git a/gone.txt b/gone.txt
deleted file mode 100644
--- a/gone.txt
+++ /dev/null
@@ -1 +0,0 @@
-bye
"""


def _response(status=200, json=None, text=''):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json or {}
    r.text = text
    return r


class SplitUnifiedDiffTests(unittest.TestCase):
    def test_splits_per_file_from_the_first_hunk(self):
        files = split_unified_diff(RAW_DIFF)
        self.assertEqual(set(files), {'api/pay.py', 'docs/new.md', 'gone.txt'})
        self.assertTrue(files['api/pay.py'].startswith('@@ -10,3 +10,3 @@'))
        self.assertIn('+    timeout = 5', files['api/pay.py'])
        self.assertNotIn('index 1111111', files['api/pay.py'])
        self.assertIn('-bye', files['gone.txt'])

    def test_empty(self):
        self.assertEqual(split_unified_diff(''), {})


class UnifiedDiffTextTests(unittest.TestCase):
    def test_hunks_without_file_header(self):
        out = unified_diff_text('a\nb\nc\n', 'a\nB\nc\n')
        self.assertTrue(out.startswith('@@'))
        self.assertIn('-b', out)
        self.assertIn('+B', out)
        self.assertNotIn('+++', out)


class GitHubDiffTextTests(unittest.TestCase):
    @patch('requests.request')
    def test_patch_is_kept(self, mock_request):
        mock_request.return_value = _response(json={
            'stats': {'additions': 1, 'deletions': 1},
            'files': [{'filename': 'api/pay.py', 'status': 'modified', 'additions': 1, 'deletions': 1,
                       'patch': '@@ -10,3 +10,3 @@\n-    timeout = 30\n+    timeout = 5'}],
        })
        diff = GitHubProvider('acme/api', 'tok').get_commit_diff('abc')
        self.assertIn('+    timeout = 5', diff['files'][0]['diff_preview'])


class BitbucketDiffTextTests(unittest.TestCase):
    @patch('requests.request')
    def test_diffstat_files_get_the_raw_diff_text(self, mock_request):
        diffstat = _response(json={'values': [
            {'status': 'modified', 'lines_added': 1, 'lines_removed': 1,
             'new': {'path': 'api/pay.py'}, 'old': {'path': 'api/pay.py'}},
            {'status': 'removed', 'lines_added': 0, 'lines_removed': 1,
             'new': None, 'old': {'path': 'gone.txt'}},
        ]})
        mock_request.side_effect = [diffstat, _response(text=RAW_DIFF)]
        diff = BitbucketProvider('acme/api', 'tok').get_commit_diff('abc123')
        by_path = {f['path']: f for f in diff['files']}
        self.assertIn('+    timeout = 5', by_path['api/pay.py']['diff_preview'])
        self.assertIn('-bye', by_path['gone.txt']['diff_preview'])
        raw_call = mock_request.call_args_list[1]
        self.assertTrue(raw_call.kwargs['url'].endswith('/repositories/acme/api/diff/abc123'))
        self.assertEqual(raw_call.kwargs['headers']['Accept'], 'text/plain')

    @patch('requests.request')
    def test_file_list_survives_when_the_diff_text_fails(self, mock_request):
        diffstat = _response(json={'values': [
            {'status': 'modified', 'lines_added': 1, 'lines_removed': 1, 'new': {'path': 'a.py'}, 'old': {'path': 'a.py'}},
        ]})
        mock_request.side_effect = [diffstat, _response(status=500)]
        diff = BitbucketProvider('acme/api', 'tok').get_commit_diff('abc123')
        self.assertEqual(diff['files'][0]['path'], 'a.py')
        self.assertEqual(diff['files'][0]['diff_preview'], '')


class AzureDevOpsDiffTextTests(unittest.TestCase):
    def _router(self, files_at):
        """Answers changes / commit / items calls from a small fake repo."""
        def handler(method, url, headers=None, params=None, **kwargs):
            if url.endswith('/changes?api-version=7.0'):
                return _response(json={'changes': [
                    {'changeType': 'edit', 'item': {'path': '/api/pay.py', 'gitObjectType': 'blob'}},
                    {'changeType': 'add', 'item': {'path': '/api/new.py', 'gitObjectType': 'blob'}},
                    {'changeType': 'edit', 'item': {'path': '/img/logo.png', 'gitObjectType': 'blob'}},
                    {'changeType': 'edit', 'item': {'path': '/api', 'isFolder': True}},
                ]})
            if '/commits/' in url:
                return _response(json={'parents': ['parent1']})
            if url.endswith('/items'):
                key = (params['path'], params['versionDescriptor.version'])
                if key not in files_at:
                    return _response(status=404)
                content = files_at[key]
                if content is None:
                    return _response(json={'contentMetadata': {'isBinary': True}})
                return _response(json={'content': content, 'contentMetadata': {}})
            return _response(status=404)
        return handler

    @patch('requests.request')
    def test_hunks_are_built_from_before_and_after(self, mock_request):
        mock_request.side_effect = self._router({
            ('/api/pay.py', 'parent1'): 'def charge(order):\n    timeout = 30\n    return post(order)\n',
            ('/api/pay.py', 'abc'): 'def charge(order):\n    timeout = 5\n    return post(order)\n',
            ('/api/new.py', 'abc'): 'print("hi")\n',
            ('/img/logo.png', 'parent1'): None,
            ('/img/logo.png', 'abc'): None,
        })
        diff = AzureDevOpsProvider('acme/shop', 'pat').get_commit_diff('abc')
        by_path = {f['path']: f for f in diff['files']}
        self.assertNotIn('/api', by_path)  # folders are not files
        pay = by_path['/api/pay.py']
        self.assertIn('-    timeout = 30', pay['diff_preview'])
        self.assertIn('+    timeout = 5', pay['diff_preview'])
        self.assertEqual((pay['additions'], pay['deletions']), (1, 1))
        self.assertIn('+print("hi")', by_path['/api/new.py']['diff_preview'])
        self.assertEqual(by_path['/img/logo.png']['diff_preview'], '')  # binary
        self.assertEqual(diff['total_additions'], 2)

    @patch('requests.request')
    def test_only_the_first_files_are_diffed(self, mock_request):
        changes = [{'changeType': 'add', 'item': {'path': f'/f{i}.py', 'gitObjectType': 'blob'}} for i in range(15)]

        def handler(method, url, headers=None, params=None, **kwargs):
            if url.endswith('/changes?api-version=7.0'):
                return _response(json={'changes': changes})
            if '/commits/' in url:
                return _response(json={'parents': ['p']})
            return _response(json={'content': 'x\n', 'contentMetadata': {}})
        mock_request.side_effect = handler
        diff = AzureDevOpsProvider('acme/shop', 'pat').get_commit_diff('abc')
        with_text = [f for f in diff['files'] if f['diff_preview']]
        self.assertEqual(len(diff['files']), 15)
        self.assertEqual(len(with_text), AzureDevOpsProvider.MAX_DIFF_FILES)


if __name__ == '__main__':
    unittest.main()
