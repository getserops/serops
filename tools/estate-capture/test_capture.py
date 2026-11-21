"""Tests for capture.py. Standard library only:

    python3 -m unittest discover -s tools/estate-capture -p 'test_*.py'
"""
import gzip
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import capture  # noqa: E402

TOKEN = 'tok_9f8e7d6c5b4a39281706'
INJECT = '2026-11-20T10:00:00+00:00'


class Fake(BaseHTTPRequestHandler):
    """SerOps API, Prometheus and Loki, enough for one incident."""
    issue_text = 'checkout payment calls time out'
    metric_names = ['checkout_requests_total']
    loki_lines = 3
    git_sha = 'abc123'
    settings_at = '2026-11-20T09:00:00Z'

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        p = url.path
        if p.startswith('/serops/api/'):
            p = p[len('/serops'):]
            if self.headers.get('Authorization') != f'Token {TOKEN}':
                return self._send({'detail': 'no'}, 401)
            if p == '/api/data/investigations/7/':
                return self._send({'id': 7, 'status': 'done', 'batch_id': 'b-7', 'services': ['checkout'],
                                   'finished_at': '2026-11-20T10:04:30+00:00',
                                   'window_start': '2026-11-20T09:58:00+00:00',
                                   'window_end': '2026-11-20T10:04:00+00:00'})
            if p == '/api/data/batches/b-7/':
                return self._send({'batch_id': 'b-7', 'model_name': 'claude-haiku-5-5', 'token_count': 1234})
            if p == '/api/data/issues/b-7/':
                return self._send([{'title': self.issue_text, 'component': 'checkout'}])
            if p in ('/api/data/batches/b-7/timeline/', '/api/data/batches/b-7/history/'):
                return self._send([])
            if p == '/api/version/':
                return self._send({'version': '1.4.0+main.test', 'git_sha': self.git_sha})
            if p == '/api/settings/ai/':
                return self._send({'default_provider': 3, 'updated_at': self.settings_at})
            if p == '/api/settings/ai/providers/':
                return self._send([{'id': 3, 'name': 'claude', 'default_model': 'claude-haiku-5-5'}])
            return self._send({'detail': 'not found'}, 404)
        if p == '/api/v1/label/__name__/values':
            return self._send({'status': 'success', 'data': self.metric_names})
        if p == '/api/v1/query_range':
            return self._send({'status': 'success', 'data': {'result': [
                {'metric': {'__name__': 'checkout_requests_total', 'outcome': 'error', 'instance': '10.1.2.3:8000'},
                 'values': [[1795168800, '1'], [1795168815, 'NaN']]}]}})
        if p == '/loki/api/v1/query_range':
            n = self.loki_lines if int(q['start']) < 1795168800 * 10**9 + 1 else 0
            return self._send({'status': 'success', 'data': {'result': [
                {'stream': {'service_name': 'checkout'},
                 'values': [[str(1795168800 * 10**9 + i), f'ERROR payment failed {i}'] for i in range(n)]}]}})
        return self._send({'error': 'unknown'}, 404)

    def log_message(self, *a):
        pass


class Base(unittest.TestCase):

    def setUp(self):
        self.server = HTTPServer(('127.0.0.1', 0), Fake)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.estate_dir = os.path.join(self.tmp, 'estate')
        self.out = os.path.join(self.tmp, 'captures')
        os.makedirs(os.path.join(self.estate_dir, 'results'))
        self.write('base_url', self.url + '/serops/api')
        self.write('token', TOKEN)
        self.write('admin.env', 'PASSWORD=hunter2hunter2\n')
        self.write('KEYS.md', '| Incident | Pass rule |\n|---|---|\n| T1 | names checkout |\n')
        self.write('results/T1-r1-investigation.json', json.dumps({'investigation': {'id': 7}}))
        self.write('results/T1-r1-inject.json', json.dumps({'started': INJECT, 'log': []}))
        self.write('results/T1-r1-revert.json', json.dumps({'at': '2026-11-20T10:05:00+00:00', 'log': []}))
        self.config = {
            'estate': 'trial', 'output': self.out, 'serops': {}, 'keys_file': 'KEYS.md', 'setup_dir': '.',
            'secret_files': ['admin.env'],
            'stores': [{'name': 'prom', 'kind': 'prometheus', 'url': self.url},
                       {'name': 'loki', 'kind': 'loki', 'url': self.url, 'selector': '{service_name="SERVICE"}'}],
        }
        self.save_config()
        git = ['git', '-C', self.estate_dir, '-c', 'user.name=t', '-c', 'user.email=t@t']
        subprocess.run(git[:3] + ['init', '-q'], check=True)
        subprocess.run(git + ['commit', '-q', '--allow-empty', '-m', 'setup'], check=True)
        Fake.issue_text, Fake.metric_names, Fake.loki_lines = 'checkout payment calls time out', \
            ['checkout_requests_total'], 3
        Fake.git_sha, Fake.settings_at = 'abc123', '2026-11-20T09:00:00Z'

    def write(self, rel, text):
        with open(os.path.join(self.estate_dir, rel), 'w') as f:
            f.write(text)

    def save_config(self):
        self.write('capture.json', json.dumps(self.config))

    def run_capture(self, *args):
        return capture.main([self.estate_dir] + list(args))

    def incident_dir(self):
        return os.path.join(self.out, 'trial', 'T1-r1')


class EndToEndTest(Base):

    def test_one_incident_is_saved_with_every_part_and_a_manifest(self):
        self.assertEqual(self.run_capture(), 0)
        d = self.incident_dir()
        self.assertEqual(sorted(os.listdir(d)), ['analysis.json', 'injection.json', 'loki.json.gz',
                                                 'manifest.json', 'prom.json.gz', 'versions.json'])
        manifest = json.load(open(os.path.join(d, 'manifest.json')))
        self.assertEqual(manifest['stores']['prom']['series_count'], 1)
        self.assertEqual(manifest['stores']['loki']['per_service']['checkout']['lines'], 3)
        self.assertEqual(manifest['secret_scan']['result'], 'clean')
        self.assertIn('not recorded', manifest['query_trail'])
        self.assertEqual(manifest['window']['captured'], {'start': '2026-11-20T09:53:00Z', 'end': '2026-11-20T10:10:00Z'})
        injection = json.load(open(os.path.join(d, 'injection.json')))
        self.assertIn('names checkout', injection['key']['row'])
        versions = json.load(open(os.path.join(d, 'versions.json')))
        self.assertEqual(versions['model']['model'], 'claude-haiku-5-5')
        self.assertEqual(versions['model']['batch_records'], 'claude-haiku-5-5')
        self.assertEqual(len(versions['estate_setup']['commit']), 40)
        prom = json.load(gzip.open(os.path.join(d, 'prom.json.gz')))
        labels = prom['series'][0]['labels']
        self.assertEqual(labels['outcome'], 'error')
        self.assertEqual(labels['instance'], '[PRIVATE_IP]:8000')       # the product's redaction ran
        self.assertEqual(prom['series'][0]['values'][1], [1795168815, None])

    def test_a_second_run_skips_a_complete_capture_and_force_redoes_it(self):
        self.assertEqual(self.run_capture(), 0)
        mtime = os.path.getmtime(os.path.join(self.incident_dir(), 'manifest.json'))
        self.assertEqual(self.run_capture(), 0)
        self.assertEqual(os.path.getmtime(os.path.join(self.incident_dir(), 'manifest.json')), mtime)
        self.assertEqual(self.run_capture('--force'), 0)
        self.assertEqual(sorted(p for p in os.listdir(os.path.join(self.out, 'trial'))), ['T1-r1'])


class FailLoudlyTest(Base):

    def assert_nothing_saved(self):
        parent = os.path.join(self.out, 'trial')
        self.assertEqual(os.listdir(parent) if os.path.exists(parent) else [], [])

    def test_an_estate_secret_in_the_data_discards_the_incident(self):
        Fake.issue_text = f'login used {TOKEN}'
        self.assertEqual(self.run_capture(), 3)
        self.assert_nothing_saved()

    def test_a_secret_stops_the_run_before_the_next_incident(self):
        for action, body in (('investigation', {'investigation': {'id': 7}}),
                             ('inject', {'started': INJECT, 'log': []})):
            self.write(f'results/T2-r1-{action}.json', json.dumps(body))
        Fake.issue_text = f'login used {TOKEN}'
        import io
        from contextlib import redirect_stderr
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(self.run_capture(), 3)
        self.assertIn('STOPPED at T1-r1', err.getvalue())
        self.assertIn('analysis.json still holds a secret of this estate', err.getvalue())
        self.assertNotIn('T2-r1', err.getvalue())
        self.assert_nothing_saved()

    def test_credentials_the_redaction_misses_discard_the_incident(self):
        # Both pass SerOps' redaction unchanged; the secret scan is the second layer.
        for text in ('alert sent to https://hooks.slack.com/services/T0000/B0000/abcdefXYZ',
                     'client-key-data: LS0tLS1CRUdJTi'):
            with self.subTest(text=text):
                Fake.issue_text = text
                self.assertEqual(self.run_capture(), 3)
                self.assert_nothing_saved()

    def test_a_store_with_no_metric_at_all_is_an_error_not_an_empty_file(self):
        Fake.metric_names = []
        self.assertEqual(self.run_capture(), 1)
        self.assert_nothing_saved()

    def test_no_log_line_for_any_service_is_an_error(self):
        Fake.loki_lines = 0
        self.assertEqual(self.run_capture(), 1)
        self.assert_nothing_saved()

    def test_an_unreachable_store_is_an_error(self):
        self.config['stores'][0]['url'] = 'http://127.0.0.1:9'
        self.save_config()
        self.assertEqual(self.run_capture(), 1)
        self.assert_nothing_saved()

    def test_a_missing_trail_is_an_error_when_the_trail_is_configured(self):
        self.config['trail'] = {'source': 'docker', 'containers': ['no-such-container-xyz']}
        self.save_config()
        self.assertEqual(self.run_capture(), 1)
        self.assert_nothing_saved()

    def test_a_serops_build_without_a_commit_is_refused(self):
        Fake.git_sha = ''
        self.assertEqual(self.run_capture(), 1)
        self.assert_nothing_saved()

    def test_ai_settings_changed_after_the_run_are_refused(self):
        Fake.settings_at = '2026-11-20T11:00:00Z'
        self.assertEqual(self.run_capture(), 1)
        self.assert_nothing_saved()

    def test_output_inside_the_repository_is_refused(self):
        self.config['output'] = os.path.join(capture.HERE, 'out')
        self.save_config()
        self.assertEqual(self.run_capture(), 2)

    def test_an_estate_without_a_setup_commit_is_refused(self):
        shutil.rmtree(os.path.join(self.estate_dir, '.git'))
        self.assertEqual(self.run_capture(), 1)
        self.assert_nothing_saved()


class KubectlTest(Base):
    """The trail and port-forwards through a fake kubectl."""

    def fake_kubectl(self, script):
        bindir = os.path.join(self.tmp, 'bin')
        os.makedirs(bindir, exist_ok=True)
        path = os.path.join(bindir, 'kubectl')
        with open(path, 'w') as f:
            f.write('#!/bin/sh\n' + script)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        old = os.environ['PATH']
        os.environ['PATH'] = bindir + os.pathsep + old
        self.addCleanup(os.environ.__setitem__, 'PATH', old)
        self.write('kubeconfig', 'apiVersion: v1\nusers:\n- user:\n    token: kubetoken-1234567890\n')
        self.config['kubeconfig'] = 'kubeconfig'

    def test_the_trail_is_read_from_every_worker_pod(self):
        line = json.dumps({'at': '2026-11-20T10:03:00Z', 'store': 'loki:3100', 'method': 'GET',
                           'url': 'http://loki:3100/loki/api/v1/query_range', 'request': '', 'status': 200,
                           'response': '{"data":{"result":[]}}'})
        self.fake_kubectl(f"""case "$*" in
  *"get pods"*) echo pod/worker-a; echo pod/worker-b ;;
  *"worker-a -- cat /tmp/serops-query-trail/investigation-7.jsonl"*) echo '{line}' ;;
  *"cat"*) echo "cat: can't open: No such file or directory" >&2; exit 1 ;;
esac
""")
        self.config['trail'] = {'namespace': 'serops', 'selector': 'app.kubernetes.io/component=celery-worker'}
        self.save_config()
        self.assertEqual(self.run_capture(), 0)
        manifest = json.load(open(os.path.join(self.incident_dir(), 'manifest.json')))
        self.assertEqual(manifest['query_trail'], {'requests': 1, 'stores': ['loki:3100']})

    def test_a_kubeconfig_token_in_the_data_discards_the_incident(self):
        self.fake_kubectl('exit 0\n')
        self.save_config()
        Fake.issue_text = 'kubetoken-1234567890'
        self.assertEqual(self.run_capture(), 3)

    def test_a_store_behind_a_service_is_reached_through_port_forward(self):
        port = self.server.server_port
        self.fake_kubectl(f'echo "Forwarding from 127.0.0.1:{port} -> 9090"; sleep 30\n')
        self.config['stores'][0] = {'name': 'prom', 'kind': 'prometheus', 'service': 'obs/svc/prometheus',
                                    'port': 9090}
        self.save_config()
        self.assertEqual(self.run_capture(), 0)


if __name__ == '__main__':
    unittest.main()
