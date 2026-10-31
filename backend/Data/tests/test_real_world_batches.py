"""
A scheduled batch built from logs as real shippers write them.

The pipeline runs for real; only the log provider (fed provider-shaped
records through the real parsers), metrics and the AI call are replaced.
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from Data.models import AIAnalyzedBatch
from Data.tests.test_investigations import PipelineMixin, make_world
from integrations.schemas import LogEntry
from Projects.models import ProjectService


def hit(source, minutes_ago=2):
    ts = (timezone.now() - timedelta(minutes=minutes_ago)).isoformat()
    return LogEntry.from_es_hit({'_id': source.get('message', source.get('msg', '')) + ts,
                                 '_source': {'@timestamp': ts, **source}})


class RealWorldScheduledBatchTest(PipelineMixin, TestCase):
    def setUp(self):
        self.org, self.project, self.env = make_world()
        for name in ('cart', 'orders', 'api'):
            ProjectService.objects.create(project=self.project, name=name)

    def run_scheduled(self, logs):
        with patch('Data.sentinel.evaluate_batch', return_value=('alert', ['errors'])):
            self.run_pipeline(logs, project_name='api', project=self.project.id,
                              environment=self.env.id, interval_minutes=15)
        return AIAnalyzedBatch.objects.get()

    def test_every_shipper_shape_reaches_the_batch(self):
        logs = [
            # Filebeat / Elastic Agent (ECS): nested service and log.level
            hit({'message': 'payment gateway timeout', 'log': {'level': 'error'},
                 'service': {'name': 'checkout', 'environment': 'production'}}),
            # OpenTelemetry exporter: WARN, environment spelled prod
            hit({'body': 'cart unreachable', 'severity_text': 'WARN', 'service.name': 'cart',
                 'deployment.environment.name': 'prod'}),
            # Pino: numeric level 50
            hit({'msg': 'order failed', 'level': 50, 'service_name': 'orders'}),
            # Unstructured: level only in the line
            hit({'message': '2026-10-27 ERROR db pool exhausted', 'service_name': 'api'}),
            # Must stay out: INFO noise, another environment, an unregistered service
            hit({'message': 'GET /healthz 200', 'level': 'info', 'service_name': 'api'}),
            hit({'message': 'staging boom', 'level': 'error', 'service_name': 'api', 'environment': 'staging'}),
            hit({'message': 'not ours', 'level': 'error', 'service_name': 'marketing'}),
        ]
        batch = self.run_scheduled(logs)
        messages = sorted(l['_source']['message'] if '_source' in l else l['message'] for l in batch.data['logs'])
        self.assertEqual(messages, ['2026-10-27 ERROR db pool exhausted', 'cart unreachable',
                                    'order failed', 'payment gateway timeout'])

    def test_first_batch_queries_its_own_window(self):
        self.run_scheduled([hit({'message': 'x', 'level': 'error', 'service_name': 'api'})])
        query = self.provider.search.call_args_list[0].args[1]
        self.assertIsNotNone(query.time_range, 'the first batch used to query all of history')
        start, end = query.time_range
        self.assertAlmostEqual((end - start).total_seconds(), 15 * 60, delta=5)

    def test_logs_written_in_the_same_millisecond_all_reach_the_batch(self):
        ts = (timezone.now() - timedelta(minutes=2)).isoformat()
        burst = [LogEntry.from_es_hit({'_id': f'id-{i}', '_source': {
            '@timestamp': ts, 'message': message, 'level': 'error', 'service_name': 'cart'}})
            for i, message in enumerate(['db pool exhausted', 'payment declined', 'cart lock timeout'])]
        batch = self.run_scheduled(burst)
        self.assertEqual(len(batch.data['logs']), 3, 'one millisecond used to keep a single log')
