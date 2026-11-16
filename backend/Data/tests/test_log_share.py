"""Every service with errors or warnings keeps a share of the log sample
(phase 3 client C3, K12: dispatch's ~3,700 errors filled the sample and
billing-worker's real warnings never reached the analysis)."""
from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from Data.log_filters import log_service
from Data.log_share import TOP_UP_RECORDS, fair_share, top_up_quiet_services
from integrations.schemas import LogEntry, LogQuery

NOW = datetime(2026, 11, 16, 19, 50, tzinfo=timezone.utc)


def entry(service, message, n=0, level='ERROR'):
    return LogEntry(timestamp=NOW - timedelta(seconds=n), message=message, level=level,
                    service=service, raw_id=f'{service}-{n}')


class FairShareTest(SimpleTestCase):
    def test_quiet_service_is_represented_and_cap_is_kept(self):
        loud = [{'component': 'dispatch', 'i': i} for i in range(3700)]
        quiet = [{'component': 'billing-worker', 'i': i} for i in range(12)]
        kept = fair_share(loud + quiet, key=lambda g: g['component'], cap=99)
        self.assertEqual(len(kept), 99)
        self.assertEqual(sum(1 for g in kept if g['component'] == 'billing-worker'), 5)
        self.assertEqual(sum(1 for g in kept if g['component'] == 'dispatch'), 94)

    def test_order_is_kept(self):
        items = [('a', i) for i in range(50)] + [('b', i) for i in range(3)]
        kept = fair_share(items, key=lambda x: x[0], cap=20)
        self.assertEqual(kept, sorted(kept, key=items.index))

    def test_single_service_is_unchanged(self):
        items = [('a', i) for i in range(300)]
        self.assertEqual(fair_share(items, key=lambda x: x[0], cap=100), items[:100])

    def test_under_the_cap_nothing_changes(self):
        items = [('a', 1), ('b', 2)]
        self.assertEqual(fair_share(items, key=lambda x: x[0], cap=100), items)

    def test_many_services_never_more_than_half_in_guarantees(self):
        items = [(f's{k}', i) for k in range(40) for i in range(10)]
        kept = fair_share(items, key=lambda x: x[0], cap=40)
        self.assertEqual(len(kept), 40)

    def test_grouped_counts_are_preserved(self):
        groups = [{'component': 'dispatch', 'count': 900}] * 120 + [{'component': 'billing', 'count': 37}]
        kept = fair_share(groups, key=lambda g: g['component'], cap=99)
        self.assertIn({'component': 'billing', 'count': 37}, kept)


class _Store:
    def __init__(self, logs, fail_for=()):
        self.logs, self.fail_for, self.queries = logs, set(fail_for), []

    def search(self, index, query):
        self.queries.append(query)
        if query.services and query.services[0] in self.fail_for:
            raise RuntimeError('store refused')
        out = [e for e in self.logs if not query.services or e.service in query.services]
        return out[:query.max_results]


class TopUpTest(SimpleTestCase):
    def setUp(self):
        self.query = LogQuery(time_range=(NOW - timedelta(minutes=5), NOW), severity=['ERROR'], max_results=100)
        self.loud = [entry('dispatch', 'no depot for region', n) for n in range(100)]
        self.quiet = [entry('billing-worker', 'rejected event version=2', n, 'WARN') for n in range(12)]

    def test_a_full_read_tops_up_the_missing_service(self):
        store = _Store(self.loud + self.quiet)
        extra = top_up_quiet_services(store, 'logs-*', self.query, self.loud,
                                      ['dispatch', 'billing-worker'], log_service)
        self.assertEqual(len(extra), 12)
        self.assertEqual(store.queries[-1].services, ['billing-worker'])
        self.assertEqual(store.queries[-1].max_results, TOP_UP_RECORDS)

    def test_a_read_under_its_cap_needs_no_top_up(self):
        store = _Store(self.quiet)
        self.assertEqual(top_up_quiet_services(store, 'logs-*', self.query, self.quiet[:5],
                                               ['dispatch', 'billing-worker'], log_service), [])
        self.assertEqual(store.queries, [])

    def test_a_failing_top_up_never_raises(self):
        store = _Store(self.loud + self.quiet, fail_for={'billing-worker'})
        self.assertEqual(top_up_quiet_services(store, 'logs-*', self.query, self.loud,
                                               ['dispatch', 'billing-worker'], log_service), [])
