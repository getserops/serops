"""Every queue a task is routed to must be consumed by the worker.

A task routed to a queue nobody consumes is queued forever and fails
silently. The Helm chart once consumed only "high_priority,celery", so
analyze_batch ("background") and the scheduler fan-out ("normal") never ran
on Kubernetes. start.sh is the Docker Compose worker; the chart's
serops.workerQueues helper lists the same four queues.
"""
import re
from pathlib import Path

from django.test import SimpleTestCase

from api.celery import app

REQUIRED_BY_CHART = {'celery', 'high_priority', 'normal', 'background'}


def _routed_queues():
    return {route['queue'] for route in app.conf.task_routes.values() if 'queue' in route}


class WorkerQueuesTest(SimpleTestCase):

    def test_start_sh_consumes_every_routed_queue(self):
        script = (Path(__file__).resolve().parents[2] / 'start.sh').read_text()
        for match in re.finditer(r'-Q\s+([\w,]+)', script):
            consumed = set(match.group(1).split(','))
            self.assertLessEqual(_routed_queues() | {'celery'}, consumed,
                                 f'start.sh worker misses queues: {_routed_queues() - consumed}')

    def test_the_chart_helper_lists_every_routed_queue(self):
        # Mirrors the list in deploy/helm/serops/templates/_helpers.tpl
        # (serops.workerQueues): add a queue to both when routing a new one.
        self.assertLessEqual(_routed_queues(), REQUIRED_BY_CHART)


class PeriodicTaskExpiryTest(SimpleTestCase):

    def test_interval_tasks_expire_before_the_next_tick(self):
        from datetime import timedelta
        for name, entry in app.conf.beat_schedule.items():
            if isinstance(entry['schedule'], timedelta):
                with self.subTest(name):
                    self.assertEqual(entry['options'].get('expires'), entry['schedule'].total_seconds())
