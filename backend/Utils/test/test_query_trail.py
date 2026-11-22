"""The opt-in query trail (Utils.query_trail): off by default, and when on,
one JSON line per store request with what SerOps asked and what it got."""

import json
import os
import shutil
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from Utils import query_trail
from Utils.outbound import GuardedSession, guarded_request


class _Answer(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('Content-Length') or 0)
        self.rfile.read(length)
        body = b'{"status":"success","data":{"result":[]}}'
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _TrailCase(SimpleTestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        env = patch.dict(os.environ, {query_trail.ENV_VAR: self.dir})
        env.start()
        self.addCleanup(env.stop)

    def lines(self, key):
        path = os.path.join(self.dir, f'{key}.jsonl')
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return [json.loads(line) for line in f]


class OffByDefaultTest(SimpleTestCase):

    def test_nothing_is_recorded_without_the_setting(self):
        with patch.dict(os.environ, {query_trail.ENV_VAR: ''}):
            with query_trail.recording('investigation-1') as path:
                self.assertIsNone(path)
                self.assertFalse(query_trail.active())
                query_trail.record('loki', 'GET', 'http://loki:3100/x')

    def test_nothing_is_recorded_outside_a_recording_block(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        with patch.dict(os.environ, {query_trail.ENV_VAR: d}):
            query_trail.record('loki', 'GET', 'http://loki:3100/x')
        self.assertEqual(os.listdir(d), [])


class RecordTest(_TrailCase):

    def test_a_session_request_is_recorded_with_its_answer_and_without_headers(self):
        server = HTTPServer(('127.0.0.1', 0), _Answer)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f'http://user:pw@127.0.0.1:{server.server_port}/api/v1/query_range?api_key=SECRET&step=15'

        with query_trail.recording('investigation-7'):
            GuardedSession().post(url, data={'query': 'up{project_name="ledger"}'},
                                  headers={'Authorization': 'Bearer TOPSECRET'}, timeout=5)

        [line] = self.lines('investigation-7')
        self.assertEqual(line['method'], 'POST')
        self.assertEqual(line['status'], 200)
        self.assertIn('project_name', line['request'])
        self.assertIn('"result":[]', line['response'])
        self.assertNotIn('pw@', line['url'])
        self.assertNotIn('SECRET', line['url'])
        self.assertIn('step=15', line['url'])
        self.assertNotIn('TOPSECRET', json.dumps(line))
        self.assertFalse(line['truncated'])

    @patch('Utils.outbound._send')
    def test_guarded_request_records_the_url_as_sent_and_failures(self, request):
        sent = MagicMock(status_code=200, content=b'[{"id": "abc"}]')
        sent.request.url = 'http://gitea.local/api/v1/repos/x/commits?sha=main'
        request.side_effect = [sent, ConnectionError('refused')]

        with query_trail.recording('batch_1'):
            guarded_request('GET', 'http://gitea.local/api/v1/repos/x/commits', params={'sha': 'main'})
            with self.assertRaises(ConnectionError):
                guarded_request('GET', 'http://gitea.local/api/v1/repos/x/commits')

        ok, failed = self.lines('batch_1')
        self.assertEqual(ok['url'], 'http://gitea.local/api/v1/repos/x/commits?sha=main')
        self.assertEqual(ok['response'], '[{"id": "abc"}]')
        self.assertIsNone(failed['status'])
        self.assertIn('refused', failed['error'])

    def test_a_long_answer_is_cut_and_marked(self):
        with patch.object(query_trail, 'MAX_BODY_CHARS', 10), query_trail.recording('k'):
            query_trail.record('loki', 'GET', 'http://loki:3100/q', response_body='x' * 50)
        [line] = self.lines('k')
        self.assertEqual(len(line['response']), 10)
        self.assertTrue(line['truncated'])

    def test_a_recording_failure_never_reaches_the_caller(self):
        with query_trail.recording('k'), patch('Utils.query_trail.os.open', side_effect=OSError('disk full')):
            query_trail.record('loki', 'GET', 'http://loki:3100/q')

    def test_the_key_cannot_leave_the_directory(self):
        with query_trail.recording('../../etc/passwd') as path:
            self.assertEqual(os.path.dirname(path), self.dir)


class SearchClientTest(_TrailCase):

    def test_elasticsearch_requests_are_recorded(self):
        from elastic_transport import Urllib3HttpNode

        from integrations.adapters.guarded_transport import guarded_es_node_class
        node = guarded_es_node_class().__new__(guarded_es_node_class())
        node._base_url = 'http://es.local:9200'
        answer = SimpleNamespace(meta=SimpleNamespace(status=200), body=b'{"hits":{"hits":[]}}')
        with patch.object(Urllib3HttpNode, 'perform_request', return_value=answer), \
                patch('integrations.adapters.guarded_transport.check_url'), \
                patch.object(type(node), 'base_url', 'http://es.local:9200'), \
                query_trail.recording('investigation-3'):
            node.perform_request('POST', '/fleet-logs-*/_search', body=b'{"query":{"match_all":{}}}')

        [line] = self.lines('investigation-3')
        self.assertEqual(line['url'], 'http://es.local:9200/fleet-logs-*/_search')
        self.assertIn('match_all', line['request'])
        self.assertEqual(line['status'], 200)
        self.assertIn('hits', line['response'])

    def test_opensearch_requests_are_recorded(self):
        from opensearchpy import Urllib3HttpConnection

        from integrations.adapters.guarded_transport import guarded_opensearch_connection_class
        cls = guarded_opensearch_connection_class()
        conn = cls.__new__(cls)
        conn.host = 'https://os.local:9200'
        with patch.object(Urllib3HttpConnection, 'perform_request', return_value=(200, {}, '{"hits":{}}')), \
                patch('integrations.adapters.guarded_transport.check_url'), \
                query_trail.recording('investigation-4'):
            status, _headers, data = conn.perform_request('GET', '/logs-*/_search', params={'size': 5}, body='{}')

        self.assertEqual((status, data), (200, '{"hits":{}}'))
        [line] = self.lines('investigation-4')
        self.assertEqual(line['url'], 'https://os.local:9200/logs-*/_search?size=5')


class GcpMonitoringTest(_TrailCase):

    def _provider(self, series):
        from integrations.adapters.gcp_monitoring import GcpCloudMonitoringProvider
        provider = GcpCloudMonitoringProvider.__new__(GcpCloudMonitoringProvider)
        provider._client = MagicMock()
        provider._client.list_time_series.return_value = iter(series)
        return provider

    def test_the_answer_is_recorded_as_it_is_consumed(self):
        provider = self._provider(['s1', 's2'])
        with query_trail.recording('investigation-9'):
            got = list(provider._list_time_series(request={'filter': 'metric.type="x"'}))
        self.assertEqual(got, ['s1', 's2'])
        [line] = self.lines('investigation-9')
        self.assertIn('metric.type', line['request'])
        self.assertEqual(len(json.loads(line['response'])), 2)

    def test_off_returns_the_client_iterator_untouched(self):
        provider = self._provider(['s1'])
        it = provider._client.list_time_series.return_value
        with patch.dict(os.environ, {query_trail.ENV_VAR: ''}):
            self.assertIs(provider._list_time_series(request={}), it)


class TaskKeysTest(_TrailCase):

    def test_an_investigation_records_under_its_id(self):
        from Data import tasks

        def collect(**kwargs):
            query_trail.record('loki', 'GET', 'http://loki:3100/q')
            return 'ok'

        with patch.object(tasks, 'create_log_batch_with_project_name', side_effect=collect):
            tasks.run_investigation.run(42)
        self.assertEqual(len(self.lines('investigation-42')), 1)

    def test_an_analysis_records_under_its_batch_id(self):
        from ai_model import tasks

        def analyse(task, batch_id, preprocessed_logs=None):
            query_trail.record('gitea', 'GET', 'http://gitea/diff')

        with patch.object(tasks, '_analyze_batch', side_effect=analyse):
            tasks.analyze_batch.run('b-2026')
        self.assertEqual(len(self.lines('b-2026')), 1)
