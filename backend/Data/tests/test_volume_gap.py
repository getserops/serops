"""Data that stopped is a finding, not a quiet window (phase 3 client C4:
L5, the log store went read-only; L3, checkout traffic stopped with no
error logged; both were reported healthy)."""
from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from Data.volume_gap import READ_CAP, assess, check_log_volume, format_data_gap
from integrations.schemas import LogEntry, LogQuery

T0 = datetime(2026, 11, 16, 20, 0, tzinfo=timezone.utc)


def entry(service, minute, level='INFO'):
    return LogEntry(timestamp=T0 + timedelta(minutes=minute, seconds=7), message='GET /x 200',
                    level=level, service=service)


def steady(service, n, minutes=10):
    return [entry(service, i % minutes) for i in range(n)]


def svc(e):
    return (e.service or '').lower()


class AssessTest(SimpleTestCase):
    def test_project_logs_stopped(self):
        gap = assess([], steady('web', 80) + steady('payments', 40), False, svc)
        self.assertTrue(gap['collapsed'])
        self.assertEqual(gap['window_logs'], 0)

    def test_one_service_went_silent(self):
        gap = assess(steady('web', 60), steady('web', 60) + steady('payments', 30), False, svc)
        self.assertFalse(gap['collapsed'])
        self.assertEqual([s['service'] for s in gap['silent_services']], ['payments'])

    def test_steady_project_is_no_gap(self):
        self.assertIsNone(assess(steady('web', 70), steady('web', 80), False, svc))

    def test_normally_quiet_project_is_no_gap(self):
        self.assertIsNone(assess([], steady('web', 12), False, svc))

    def test_bursty_job_is_no_gap(self):
        burst = [entry('reindex', 3) for _ in range(40)]  # one minute, then nothing
        self.assertIsNone(assess(steady('web', 60), steady('web', 60) + burst, False, svc))

    def test_restarted_service_still_logging_is_no_gap(self):
        self.assertIsNone(assess(steady('web', 60) + [entry('payments', 9)],
                                 steady('web', 60) + steady('payments', 30), False, svc))

    def test_full_current_read_is_never_a_gap(self):
        self.assertIsNone(assess(steady('web', READ_CAP), steady('web', 60) + steady('payments', 30),
                                 True, svc))


class FakeStore:
    def __init__(self, current, previous, fail=False):
        self.current, self.previous, self.fail, self.queries = current, previous, fail, []

    def search(self, index, query):
        self.queries.append(query)
        if self.fail:
            raise RuntimeError('store refused')
        return self.current if len(self.queries) == 1 else self.previous


class CheckLogVolumeTest(SimpleTestCase):
    def query(self):
        return LogQuery(time_range=(T0, T0 + timedelta(minutes=10)), severity=['ERROR'], project='studio',
                        services=['web'], max_results=5000)

    def test_reads_every_level_this_window_then_the_window_before(self):
        store = FakeStore([], steady('web', 80))
        gap = check_log_volume(store, 'logs-*', self.query())
        self.assertTrue(gap['collapsed'])
        first, second = store.queries
        self.assertIsNone(first.severity)
        self.assertIsNone(first.services)
        self.assertEqual(first.max_results, READ_CAP)
        self.assertEqual(second.time_range, (T0 - timedelta(minutes=10), T0))

    def test_a_full_window_skips_the_second_read(self):
        store = FakeStore(steady('web', READ_CAP), steady('web', 80))
        self.assertIsNone(check_log_volume(store, 'logs-*', self.query()))
        self.assertEqual(len(store.queries), 1)

    def test_a_refused_read_is_no_gap_and_no_error(self):
        self.assertIsNone(check_log_volume(FakeStore([], [], fail=True), 'logs-*', self.query()))

    def test_prompt_text(self):
        facts, services = format_data_gap({'window_logs': 0, 'previous_logs': 300, 'previous_capped': True,
                                           'collapsed': True,
                                           'silent_services': [{'service': 'payments', 'previous_logs': 40}]})
        self.assertIn('300+', facts)
        self.assertIn('fell by 90 %', facts)
        self.assertIn('payments: 0 records now', services)
