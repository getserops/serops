"""Tests for build_seed.py. Standard library only, synthetic data only:

    python3 -m unittest discover -s tools/demo-seed -p 'test_*.py'
"""
import contextlib
import copy
import gzip
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_seed as bs  # noqa: E402

# An invented estate. Nothing here comes from a real capture.
ESTATE, TAG = 'depot', 'Z1-r1'
ORG = 'Northwind'
NODE_A = 'gke-zz-depot-default-pool-0a1b2c3d-ab12'
NODE_B = 'gke-zz-depot-default-pool-0a1b2c3d-cd34'
CLUSTER = 'zz-depot'
CLOUD = 'northwind-prod-42'
AUTHOR = 'jquimby'
REQUESTER = 'Jane Roe'
PUBLIC_IP = '34.90.1.2'
PRIVATE_IP = '10.4.0.9'
MAIL = 'jquimby@northwind.test'
REPO = 'github.com/jquimby/depot-infra'
T0 = datetime(2026, 3, 10, 12, 0, 0, tzinfo=timezone.utc)   # window start
BATCH_TS = T0 + timedelta(minutes=8)


def slurp(path):
    with open(path, 'rb') as f:
        return f.read()


def iso(dt, frac='.000000', zone='+00:00'):
    return dt.strftime('%Y-%m-%dT%H:%M:%S') + frac + zone


def epoch(dt):
    return int((dt - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds())


def make_logs(count):
    logs = []
    for n in range(count):
        at = T0 + timedelta(seconds=n * 0.4)
        ms = '.%06d' % (at.microsecond)
        host = NODE_A if n % 2 else NODE_B
        msg = '%s INFO stock: tick %d from %s' % (at.strftime('%Y-%m-%d %H:%M:%S,%f')[:23], n, PRIVATE_IP)
        if n == 500:
            msg = '%s ERROR stock: Could not reserve pallet P-77: LockTimeout after 4000 ms' % (
                at.strftime('%Y-%m-%d %H:%M:%S,%f')[:23])
        if n == 640:
            msg = 'upstream http://billing.depot:8080/charge refused; see https://pip.pypa.io/warnings and mail %s' % MAIL
        logs.append({'_id': '%d-%04x' % (epoch(at) * 10 ** 9 + at.microsecond * 1000, n), '_index': 'depot-logs',
                     '_source': {'@timestamp': at.strftime('%Y-%m-%dT%H:%M:%S') + ms + '+00:00',
                                 'time': epoch(at) * 1000.0 + at.microsecond // 1000, 'message': msg,
                                 'service': 'stock' if n % 3 else 'billing', 'host': host,
                                 'organisation_name': ORG, 'project_name': ESTATE,
                                 'kubernetes': {'host': host, 'pod_ip': PRIVATE_IP, 'namespace_name': 'depot',
                                                'labels': {'topology/zone': 'zone-a'}}}})
    logs.reverse()          # newest first, as SerOps stores them
    return logs


def make_capture(root, logs=1000, issue_created=None, capture_occurrences=1, runtime_occurrences=1):
    """A capture directory and its run-time file, in the capture tool's layout."""
    directory = os.path.join(root, 'captures', ESTATE, TAG)
    os.makedirs(directory)
    log_rows = make_logs(logs)
    cited_at = T0 + timedelta(seconds=500 * 0.4)
    batch_id = '%s-batch-%s-9d63' % (ESTATE, BATCH_TS.strftime('%Y%m%d%H%M%S'))
    correlated = {
        'severity': 'CRITICAL', 'component': 'stock', 'description': 'Reservations time out.',
        'root_cause': "Commit 4d5abd99 lowered the lock timeout; errors 'Could not reserve pallet' from 12:03:20 "
                      'on %s and %s.' % (NODE_A, NODE_B),
        'reasoning': ['Both hosts (ab12: 3, cd34: 2) log it.'],
        'occurrences': {'count': 1, 'timestamps': [iso(cited_at)]},
        'evidence_sources': {
            'code': ['4d5abd99'], 'cicd': [], 'traces': ['aaaabbbbccccdddd'],
            'logs': ['[%s] [ERROR] [stock] Could not reserve pallet P-77: LockTimeout ... 4000 ms [x3, 2 hosts]'
                     % cited_at.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                     '[%s] [ERROR] [stock] a line that is in no log' % iso(T0 + timedelta(minutes=7, seconds=30))],
            'metrics': ['Kubernetes change %s: Deployment stock rollout' % (T0 + timedelta(minutes=3)).strftime(
                '%Y-%m-%dT%H:%M:%SZ')]},
        'caused_by_commits': ['4d5abd99'],
    }
    issue = {
        'id': 7, 'batch': 3, 'batch_id_str': batch_id, 'batch_timestamp': iso(BATCH_TS, '.464258', 'Z'),
        'severity': 'CRITICAL', 'description': 'Reservations time out.', 'recommendation': 'Roll back 4d5abd99.',
        'root_cause': correlated['root_cause'], 'reasoning': '1. Both hosts (ab12: 3, cd34: 2) log it.',
        'confidence': 'HIGH', 'confidence_display': 'High',
        'created_at': issue_created or iso(BATCH_TS + timedelta(seconds=30), '.889088', 'Z'),
        'issue_type': 'DATABASE_ERROR', 'issue_type_display': 'Database Error', 'scope': 'SERVICE',
        'component': 'stock', 'affected_services': ['billing'], 'environment': 'production', 'status': 'OPEN',
        'status_display': 'Open', 'occurrence_count': runtime_occurrences, 'muted_until': None,
        'last_seen_at': iso(BATCH_TS + timedelta(seconds=31), '.889131', 'Z'), 'acknowledged_at': None,
        'project': 1, 'project_name': ESTATE, 'error_class': 'CONFIG_ERROR',
        'error_class_display': 'Configuration error', 'error_target': 'lock_timeout',
        'has_commit_correlation': True, 'has_metric_correlation': False,
        'linked_commits': [{'sha': '4d5abd99', 'provider': 'unknown', 'project_id': None}],
        'metric_correlation_type': '', 'correlation_confidence': 'MEDIUM', 'metric_anomaly_type': '',
        'correlation_details': {}, 'has_cicd_correlation': False,
        'correlation_summary': [{'type': 'commit', 'value': '4d5abd99'}], 'informed_by': {'count': 0, 'items': []},
        'resolved_at': None, 'resolved_by_name': None, 'resolution_root_cause': None, 'resolution_fix': None,
        'related_traces': {'trace_count': 0},
    }
    capture_issue = dict(issue, occurrence_count=capture_occurrences)
    if capture_occurrences != runtime_occurrences:
        capture_issue['last_seen_at'] = iso(BATCH_TS + timedelta(minutes=4), '.000001', 'Z')
    result = {'summary': {'overall_health': 'DEGRADED'}, 'correlated_issues': [correlated]}
    data = {
        'logs': log_rows, 'cicd_logs': [], 'metrics': {'cpu': [
            {'time': (T0 + timedelta(seconds=15 * n)).strftime('%Y-%m-%dT%H:%M:%S.024000'), 'value': 1773144000 + n,
             'series_key': 'stock'} for n in range(4)]},
        'metrics_summary': {'time_range': {'start': iso(T0), 'end': iso(BATCH_TS)}},
        'traces': {'source': 'otlp', 'top_errors': [{'trace_id': 'aaaabbbbccccddddaaaabbbbccccdddd',
                                                      'start_time': iso(T0 + timedelta(minutes=5))}], 'top_slow': []},
        'statistics': {'total_logs': logs, 'project_name': ESTATE,
                       'time_range': {'start': iso(T0), 'end': iso(BATCH_TS)}},
        'code_changes': [{'sha': '4d5abd99', 'author': AUTHOR, 'branch': 'main', 'message': 'stock: lock timeout',
                          'timestamp': iso(T0 + timedelta(minutes=2), ''), 'files': [
                              {'path': 'c9/stock.yaml', 'diff': '-timeout: 30\n+timeout: 4'}]}],
        'change_events': [{'count': 1, 'service': 'cache', 'timestamp': iso(T0 + timedelta(minutes=3)),
                           'message': '1:M %s * Ready, signal (%d)' % (
                               (T0 + timedelta(minutes=3)).strftime('%d %b %Y %H:%M:%S.419'),
                               epoch(T0 + timedelta(minutes=3)))}],
        'analysis_result': result,
        'correlation_results': {'correlations': {'span_error_to_log_error': [
            {'service': 'stock', 'trace_id': 'aaaabbbbccccddddaaaabbbbccccdddd',
             'sample_log_message': log_rows[len(log_rows) - 1 - 500]['_source']['message'][:60]}]}},
    }
    batch = {
        'id': 3, 'batch_id': batch_id, 'timestamp': iso(BATCH_TS, '.464258', 'Z'), 'issue_count': 1, 'data': data,
        'logs_analyzed': logs, 'created_at': iso(BATCH_TS + timedelta(seconds=1), '.833306', 'Z'),
        'indices_covered': ['depot-logs-*'], 'token_count': 6103, 'analysis_text': correlated['root_cause'],
        'analyzed_at': iso(BATCH_TS + timedelta(seconds=29), '.863533', 'Z'), 'model_name': 'claude',
        'sentinel_decision': 'manual', 'sentinel_triggers': [], 'ai_skipped': False, 'logs_raw_count': logs,
        'logs_after_severity_filter': logs, 'logs_unique_patterns': 3, 'logs_sent_to_ai': 3, 'trigger': 'manual',
        'investigation': 4, 'project': 1, 'deployment': None, 'issues': [capture_issue], 'analysis': result,
        'metrics_summary': {'total_logs': logs}, 'timing': {'created_at': iso(BATCH_TS)},
    }
    investigation = {
        'id': 4, 'status': 'done', 'status_label': 'Done', 'project': {'id': 1, 'name': ESTATE},
        'environment': {'id': 3, 'name': 'production'}, 'deployment': None, 'services': [],
        'window_start': iso(T0, '.023965'), 'window_end': iso(BATCH_TS, '.108585'), 'hint': '',
        'notify_routing': False, 'counts': {'logs': logs}, 'error_code': '', 'error': '',
        'requested_by': {'id': 1, 'name': REQUESTER}, 'created_at': iso(BATCH_TS, '.237103'),
        'started_at': iso(BATCH_TS, '.464258'), 'finished_at': iso(BATCH_TS + timedelta(seconds=30), '.817723'),
        'batch_id': batch_id, 'issue_count': 1,
    }
    timeline = {'batch_id': batch_id, 'event_count': 2, 'causal_pairs': [], 'events': [
        {'time': iso(T0 + timedelta(minutes=2), ''), 'kind': 'deploy', 'service': '', 'summary': 'stock: lock timeout',
         'detail': {'sha': '4d5abd99', 'author': AUTHOR}},
        {'time': log_rows[len(log_rows) - 1 - 640]['_source']['@timestamp'], 'kind': 'log', 'service': 'billing',
         'summary': log_rows[len(log_rows) - 1 - 640]['_source']['message'][:40], 'detail': {}}]}
    analysis = {'investigation': investigation, 'batch': batch,
                'issues': {'results': [capture_issue], 'pagination': {}, 'summary': {'filter_applied': 'ALL'}},
                'timeline': timeline,
                'history': {'batch_id': batch_id, 'analysis_history': [
                    {'is_primary': True, 'model_name': 'claude', 'analyzed_at': iso(BATCH_TS + timedelta(seconds=29)),
                     'analysis_result': result}]}}
    captured = BATCH_TS + timedelta(minutes=9)
    injection = {'incident': 'Z1', 'round': 'r1',
                 'inject': {'action': 'inject', 'started': iso(T0 + timedelta(minutes=2)),
                            'at': iso(T0 + timedelta(minutes=3)),
                            'log': [{'commit': 'stock: lock timeout', 'path': 'c9/stock.yaml',
                                     'sha': '4d5abd995fa31a6467289e0b660f8be45341aac7', 'rc': 0}]},
                 'revert': {'action': 'revert', 'started': iso(BATCH_TS + timedelta(minutes=1)),
                            'at': iso(BATCH_TS + timedelta(minutes=2)),
                            'log': [{'step': '-n depot rollout undo deploy/stock', 'rc': 0}]},
                 'fault_started': (T0 + timedelta(minutes=2)).strftime('%Y-%m-%dT%H:%M:%SZ'),
                 'fault_reverted': (BATCH_TS + timedelta(minutes=2)).strftime('%Y-%m-%dT%H:%M:%SZ'),
                 'services': ['stock', 'billing'],
                 'key': {'file': '2026-03-01-PREREG.md', 'header': '| # | Injection |', 'row': '| Z1 | lock timeout |'}}
    versions = {'serops': {'version': 'main-1', 'git_sha': 'abc1234',
                           'built_at': (T0 - timedelta(hours=3)).strftime('%Y-%m-%dT%H:%M:%SZ')},
                'estate_setup': {'dir': '.', 'commit': 'f' * 40, 'uncommitted_changes': 0},
                'model': {'batch_records': 'claude', 'provider': 'claude', 'model': 'claude-sonnet-5-5',
                          'source': 'AI settings', 'settings_updated_at': iso(T0 - timedelta(hours=2), '.019406', 'Z')},
                'capture_tool_commit': 'a' * 40}
    span = {'span_id': '5ef1a4da48ae3759', 'parent_span_id': '', 'service_name': 'stock', 'operation_name': 'GET',
            'kind': 'SERVER', 'start_time': iso(T0 + timedelta(minutes=5), '.930000', 'Z'),
            'end_time': iso(T0 + timedelta(minutes=5), '.956896', 'Z'), 'duration_ms': 26, 'status_code': 'ERROR',
            'status_message': '', 'attributes': {'host.name': NODE_A, 'network.peer.address': PUBLIC_IP,
                                                 'url.full': 'http://billing.depot:8080/charge'}, 'events': []}
    trace = {'trace_id': 'aaaabbbbccccddddaaaabbbbccccdddd', 'root_service_name': 'stock', 'root_operation': 'GET',
             'start_time': span['start_time'], 'end_time': span['end_time'], 'duration_ms': 26, 'span_count': 1,
             'error_span_count': 1, 'status_code': 'ERROR', 'spans': [span]}
    store = {'kind': 'serops-traces', 'store': 'serops-traces',
             'window': {'start': iso(T0, '', 'Z'), 'end': iso(captured, '', 'Z')},
             'services': {'stock': {'traces': 1, 'truncated': False, 'items': [trace]},
                          'billing': {'traces': 1, 'truncated': False, 'items': [trace]}}}
    other = {'kind': 'prometheus', 'series': [{'labels': {'cluster_name': CLUSTER, 'project_id': CLOUD,
                                                          'instance': '%s:9100' % PUBLIC_IP, 'node': NODE_A,
                                                          'repo': 'https://%s.git' % REPO}, 'values': []}]}
    manifest = {'estate': ESTATE, 'incident': 'Z1', 'round': 'r1', 'captured_at': iso(captured, '', 'Z'),
                'window': {'captured': {'start': iso(T0 - timedelta(minutes=5), '', 'Z'), 'end': iso(captured, '', 'Z')}},
                'stores': {'serops-traces': {'kind': 'serops-traces', 'truncated': False},
                           'prometheus': {'kind': 'prometheus', 'truncated': False}}}
    for name, doc in (('analysis.json', analysis), ('injection.json', injection), ('versions.json', versions),
                      ('manifest.json', manifest)):
        with open(os.path.join(directory, name), 'w') as f:
            json.dump(doc, f)
    for name, doc in (('serops-traces.json.gz', store), ('prometheus.json.gz', other)):
        with gzip.open(os.path.join(directory, name), 'wt') as f:
            json.dump(doc, f)
    results = os.path.join(root, 'estates', ESTATE, 'results')
    os.makedirs(results)
    with open(os.path.join(results, '%s-investigation.json' % TAG), 'w') as f:
        json.dump({'incident': 'Z1', 'round': 'r1', 'investigation': investigation, 'seconds': 30,
                   'issues': {'results': [issue], 'pagination': {}, 'summary': {}}}, f)
    return os.path.join(root, 'captures'), os.path.join(root, 'estates')


REAL_VALUES = [NODE_A, NODE_B, CLUSTER, CLOUD, AUTHOR, REQUESTER, PUBLIC_IP, PRIVATE_IP, MAIL, 'northwind',
               'jquimby/depot-infra']


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='seed-test-')
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.selection = [(ESTATE, TAG)]

    def capture(self, **kw):
        self.captures, self.runtime = make_capture(self.root, **kw)
        self.rmap, _ = bs.discover(self.captures, self.runtime, self.selection)
        return self.rmap

    def build(self, **kw):
        self.out = os.path.join(self.root, 'out')
        self.private = os.path.join(self.root, 'private')
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            code, rows = bs.build_all(self.captures, self.runtime, self.rmap, self.out, self.private,
                                      self.selection, **kw)
        self.printed = printed.getvalue()
        return code, rows

    def seed(self):
        return bs.load_json(os.path.join(self.out, '%s-%s.json.gz' % (ESTATE, TAG)))

    def index(self):
        return bs.load_json(os.path.join(self.out, 'index.json'))


class TrimTest(Base):
    def test_cited_first_and_last_lines_survive_and_counts_are_kept(self):
        self.capture()
        code, rows = self.build()
        self.assertEqual(code, 0)
        seed = self.seed()
        logs = seed['batch']['data']['logs']
        trim = seed['trim']
        self.assertEqual((trim['logs_total'], trim['logs_kept'], len(logs)), (1000, 300, 300))
        messages = [l['_source']['message'] for l in logs]
        self.assertTrue(any('Could not reserve pallet P-77' in m for m in messages))          # evidence_sources
        self.assertTrue(any('upstream http://billing.depot:8080/charge' in m for m in messages))   # timeline
        self.assertIn('tick 0 ', messages[-1])               # first of the window (newest-first order kept)
        self.assertIn('tick 999 ', messages[0])              # last of the window
        self.assertEqual(trim['evidence_lines_found'], 1)
        self.assertEqual(trim['evidence_lines_kept'], 1)
        # The cited line that exists in no log is named, not silently dropped.
        self.assertEqual(trim['evidence_references_not_located'],
                         ['analysis_result[0].correlated_issues[0].evidence_sources.logs[1]'])
        # Every figure of the analysis is as captured.
        self.assertEqual(seed['batch']['logs_analyzed'], 1000)
        self.assertEqual(seed['batch']['token_count'], 6103)
        self.assertEqual(seed['batch']['data']['statistics']['total_logs'], 1000)

    def test_kept_lines_are_not_altered(self):
        logs = make_logs(700)
        refs = bs.match_evidence(bs.collect_evidence([], [], {}, {}, []), logs)
        kept, stats = bs.trim_logs(logs, refs, 300)
        self.assertEqual(stats['logs_kept'], 300)
        originals = {l['_id']: l for l in make_logs(700)}
        for line in kept:
            self.assertEqual(line, originals[line['_id']])
        self.assertEqual([l['_id'] for l in kept], [l['_id'] for l in logs if l['_id'] in {k['_id'] for k in kept}])

    def test_evidence_is_matched_by_id_time_and_text(self):
        logs = make_logs(900)
        by_n = {int(l['_source']['message'].split('tick ')[1].split(' ')[0]): l
                for l in logs if 'tick ' in l['_source']['message']}
        result = {'correlated_issues': [{'evidence_sources': {'logs': [
            '[%s] [INFO] [stock] tick 301 from ...' % by_n[301]['_source']['@timestamp'],
            'stock: tick 777 from']}, 'occurrences': {'timestamps': [by_n[411]['_source']['@timestamp']]}}]}
        correlations = {'x': [{'log_id': by_n[123]['_id']}]}
        refs = bs.match_evidence(bs.collect_evidence([result], [], correlations, {}, []), logs)
        kept, stats = bs.trim_logs(logs, refs, 50)
        ids = {l['_id'] for l in kept}
        for n in (301, 777, 411, 123, 0, 899):
            self.assertIn(by_n[n]['_id'], ids, n)
        self.assertEqual(len(kept), 50)
        self.assertEqual(stats['evidence_references_not_located'], [])

    def test_cited_lines_are_kept_even_past_the_limit(self):
        logs = make_logs(400)
        result = {'correlated_issues': [{'occurrences': {'timestamps': [l['_source']['@timestamp'] for l in logs[:350]]}}]}
        refs = bs.match_evidence(bs.collect_evidence([result], [], {}, {}, []), logs)
        kept, stats = bs.trim_logs(logs, refs, 300)
        self.assertGreaterEqual(len(kept), 350)
        self.assertTrue(stats['over_limit'])
        self.assertEqual(stats['evidence_lines_kept'], stats['evidence_lines_found'])

    def test_short_log_is_kept_whole(self):
        logs = make_logs(20)
        kept, stats = bs.trim_logs(logs, bs.match_evidence([], logs), 300)
        self.assertEqual((len(kept), stats['logs_total'], stats['logs_kept']), (20, 20, 20))


class RenameTest(Base):
    def test_discovery_finds_the_names_in_every_file(self):
        rmap = self.capture()
        self.assertIn(ORG, rmap['organisation'])
        self.assertIn(CLOUD, rmap['cloud_project'])            # only in a store file
        self.assertIn(CLUSTER, rmap['cluster'])
        self.assertEqual(rmap['cluster'][CLUSTER], 'acme-depot-cluster')
        self.assertIn(NODE_A, rmap['host'])
        self.assertEqual(rmap['host'][NODE_A.rsplit('-', 1)[0]], 'acme-depot-nodes')
        self.assertEqual(rmap['host_alias'], {'depot': {'ab12': 'node-1', 'cd34': 'node-2'}})
        self.assertIn(PUBLIC_IP, rmap['ip'])
        self.assertIn(PRIVATE_IP, rmap['ip'])
        self.assertIn(MAIL, rmap['email'])
        self.assertIn(AUTHOR, rmap['person'])
        self.assertIn(REQUESTER, rmap['person'])
        self.assertIn(REPO, rmap['repo'])
        self.assertIn('pip.pypa.io', rmap['url_host_keep'])
        self.assertTrue(bs.ip_allowed(rmap['ip'][PUBLIC_IP]))
        self.assertTrue(rmap['ip'][PRIVATE_IP].startswith('10.20.'))
        self.assertTrue(rmap['ip'][PUBLIC_IP].startswith(('192.0.2.', '198.51.100.', '203.0.113.')))

    def test_third_party_companies_and_domains_are_renamed_and_checked(self):
        rmap = self.capture()
        rmap['third_party'] = {'registry.bigcorp.test/shop-ci/shop-demo': 'registry.acme.example/{estate}',
                               'CARDCO': 'AcmeCard', 'cardco_debit': 'acmecard_debit'}
        renamer = bs.Renamer(rmap, ESTATE)
        out = renamer.walk({'image': 'registry.bigcorp.test/shop-ci/shop-demo/pay:v1',
                            'log': 'cannot process cardco_debit cards. Only CardCo is accepted; discardcos stays'})
        self.assertEqual(out['image'], 'registry.acme.example/%s/pay:v1' % ESTATE)
        self.assertEqual(out['log'], 'cannot process acmecard_debit cards. Only AcmeCard is accepted; discardcos stays')
        self.assertEqual(renamer.counts['third_party'], 3)
        self.assertIn(('third_party', 'CARDCO', 'bounded'), bs.real_values(rmap))

    def test_path_prefix_of_the_test_setup_is_removed_at_the_start_of_a_path_only(self):
        rmap = self.capture()
        rmap['path_prefix'] = {'t9/app/': 'app/'}
        renamer = bs.Renamer(rmap, ESTATE)
        out = renamer.walk({'path': 't9/app/jobs.yaml',
                            'text': "Commit 1a2b3c4d (t9/app/redis.yaml, 'cap memory')",
                            'id': 'run-0a1bt9/app/0'})
        self.assertEqual(out['path'], 'app/jobs.yaml')
        self.assertEqual(out['text'], "Commit 1a2b3c4d (app/redis.yaml, 'cap memory')")
        self.assertEqual(out['id'], 'run-0a1bt9/app/0')
        self.assertEqual(renamer.counts['path_prefix'], 2)
        self.assertIn(('path_prefix', 't9/app/', 'plain'), bs.real_values(rmap))

    def test_discovery_is_stable(self):
        first = self.capture()
        again, _ = bs.discover(self.captures, self.runtime, self.selection, copy.deepcopy(first))
        self.assertEqual(first, again)

    def test_renaming_is_consistent_in_keys_values_and_free_text(self):
        rmap = self.capture()
        renamer = bs.Renamer(rmap, ESTATE)
        doc = {'organisation_name': ORG, 'title': 'Northwind depot review', 'author': AUTHOR,
               'requested_by': REQUESTER, NODE_A: {'pods': [NODE_A, 'x on %s and %s' % (NODE_A.upper(), NODE_B)]},
               'text': 'hosts ab12: 3, cd34: 2; id zab12z stays; by %s <%s>; home /home/x%s/' % (AUTHOR, MAIL, AUTHOR),
               'labels': {'cluster': CLUSTER, 'project_id': CLOUD, 'uri': 'https://%s/commit/1' % REPO},
               'net': 'peer %s and %s, bind 0.0.0.0, lo 127.0.0.1, version 1.2.3.4.5' % (PUBLIC_IP, PRIVATE_IP),
               'mail': 'someone.else@corp.test wrote', 'n': 5, 'none': None}
        out = renamer.walk(doc)
        text = json.dumps(out)
        for real in REAL_VALUES + ['corp.test']:
            self.assertNotIn(real.lower(), text.lower(), real)
        node_a, node_b = rmap['host'][NODE_A], rmap['host'][NODE_B]
        self.assertEqual(out['organisation_name'], 'Acme Cloud')
        self.assertEqual(out['title'], 'Acme Cloud depot review')
        self.assertEqual(out['author'], rmap['person'][AUTHOR]['name'])
        self.assertEqual(out['requested_by'], rmap['person'][REQUESTER]['name'])
        self.assertIn(node_a, out)                                     # the key was renamed too
        self.assertEqual(out[node_a]['pods'], [node_a, 'x on %s and %s' % (node_a, node_b)])
        self.assertIn('hosts node-1: 3, node-2: 2; id zab12z stays', out['text'])
        self.assertIn('<%s>' % rmap['person'][AUTHOR]['email'], out['text'])
        self.assertEqual(out['labels'], {'cluster': 'acme-depot-cluster', 'project_id': rmap['cloud_project'][CLOUD],
                                         'uri': 'https://git.acme.example/acme-cloud/depot/commit/1'})
        self.assertIn('bind 0.0.0.0, lo 127.0.0.1, version 1.2.3.4.5', out['net'])
        self.assertIn('peer %s and %s,' % (rmap['ip'][PUBLIC_IP], rmap['ip'][PRIVATE_IP]), out['net'])
        self.assertRegex(out['mail'], r'^user-[0-9a-f]{6}@acme\.example wrote$')
        self.assertEqual((out['n'], out['none']), (5, None))
        # The same real value gives the same replacement on a second pass and in another renamer.
        self.assertEqual(bs.Renamer(rmap, ESTATE).walk(doc), out)

    def test_the_organisation_name_as_free_text_is_left_to_the_project_rule(self):
        # The organisation name is replaced where a field names the organisation;
        # an estate name is also the project name, which is kept.
        rmap = dict(bs.empty_map(), organisation={'Depot': 'Acme Cloud'}, kept_project_names=['depot'])
        doc = {'organisation_name': 'Depot', 'project_name': 'depot', 'text': 'the Depot project, ns depot'}
        out = bs.Renamer(rmap, ESTATE).walk(doc)
        self.assertEqual(out, dict(doc, organisation_name='Acme Cloud'))
        self.assertEqual(bs.real_values(rmap), [])

    def test_unknown_addresses_still_get_placeholders(self):
        renamer = bs.Renamer(bs.empty_map(), ESTATE)
        out = renamer.text('from 8.8.4.4 and 192.168.7.7 by x@y.org')
        for m in bs.RX_IP.finditer(out):
            self.assertTrue(bs.ip_allowed(m.group(0)), m.group(0))
        self.assertNotIn('y.org', out)
        self.assertEqual(out, bs.Renamer(bs.empty_map(), ESTATE).text('from 8.8.4.4 and 192.168.7.7 by x@y.org'))

    def test_converted_file_holds_no_real_value(self):
        self.capture()
        code, _ = self.build()
        self.assertEqual(code, 0)
        for name in os.listdir(self.out):
            text = bs.read_text(os.path.join(self.out, name)).lower()
            for real in REAL_VALUES:
                self.assertNotIn(real.lower(), text, '%s in %s' % (real, name))
        seed = self.seed()
        self.assertEqual(seed['organisation'], {'name': 'Acme Cloud', 'slug': 'acme-cloud'})
        self.assertEqual(seed['project']['name'], 'Depot')
        self.assertEqual(seed['investigation']['requested_by'], self.rmap['person'][REQUESTER]['name'])
        self.assertEqual(seed['batch']['data']['code_changes'][0]['author'], self.rmap['person'][AUTHOR]['name'])
        self.assertEqual(seed['batch']['data']['code_changes'][0]['sha'], '4d5abd99')            # kept
        self.assertEqual(seed['batch']['data']['code_changes'][0]['message'], 'stock: lock timeout')
        self.assertIn('node-1: 3, node-2: 2', seed['issues'][0]['reasoning'])
        # Nothing real is printed either.
        for real in REAL_VALUES:
            self.assertNotIn(real.lower(), self.printed.lower())


class SeedShapeTest(Base):
    def test_derived_fields_are_left_out_and_facts_are_kept(self):
        self.capture()
        self.build()
        seed = self.seed()
        for key in bs.BATCH_DROP:
            self.assertNotIn(key, seed['batch'], key)
        for key in bs.ISSUE_DROP:
            self.assertNotIn(key, seed['issues'][0], key)
        for key in bs.INVESTIGATION_DROP:
            self.assertNotIn(key, seed['investigation'], key)
        self.assertEqual(seed['batch']['trigger'], 'manual')
        self.assertEqual(seed['batch']['sentinel_decision'], 'manual')
        self.assertEqual(seed['batch']['model_name'], 'claude')
        self.assertEqual(seed['model']['used'], 'claude-sonnet-5-5')
        self.assertEqual(len(seed['batch']['analysis_history']), 1)
        self.assertEqual(seed['investigation']['project'], ESTATE)
        self.assertEqual(seed['investigation']['environment'], 'production')
        self.assertEqual(seed['issues'][0]['capture_ref'], 'depot-issue-7')
        self.assertEqual(seed['injection']['revert']['log'][0]['step'], '-n depot rollout undo deploy/stock')
        self.assertNotIn('file', seed['injection']['pre_registered_key'])
        self.assertEqual(seed['anchor'], seed['batch']['timestamp'])

    def test_ai_usage_is_a_null_placeholder(self):
        self.capture()
        self.build()
        seed = self.seed()
        self.assertIn('ai_usage', seed)
        self.assertIsNone(seed['ai_usage'])
        self.assertEqual(seed['ai_usage_reason'], 'not recorded in the capture; estate database deleted')
        self.assertIsNone(self.index()['ai_usage']['value'])

    def test_traces_come_from_the_store_file_only(self):
        self.capture()
        self.build()
        traces = self.seed()['traces']
        self.assertTrue(traces['available'])
        self.assertEqual(len(traces['items']), 1)                      # the same trace under two services, once
        self.assertEqual(set(traces['cited_found']), {'aaaabbbbccccdddd', 'aaaabbbbccccddddaaaabbbbccccdddd'})
        self.assertEqual(traces['cited_missing'], [])
        self.assertEqual(traces['items'][0]['spans'][0]['attributes']['url.full'], 'http://billing.depot:8080/charge')

    def test_no_trace_store_is_recorded_not_invented(self):
        self.capture()
        directory = os.path.join(self.captures, ESTATE, TAG)
        os.remove(os.path.join(directory, 'serops-traces.json.gz'))
        manifest = bs.load_json(os.path.join(directory, 'manifest.json'))
        del manifest['stores']['serops-traces']
        with open(os.path.join(directory, 'manifest.json'), 'w') as f:
            json.dump(manifest, f)
        self.build()
        traces = self.seed()['traces']
        self.assertFalse(traces['available'])
        self.assertEqual(traces['items'], [])
        self.assertIn('could not', traces['reason'])
        self.assertEqual(len(traces['cited_missing']), 2)

    def test_issues_come_from_run_time_and_the_capture_version_is_kept_when_it_differs(self):
        self.capture(capture_occurrences=3, runtime_occurrences=1)
        self.build()
        seed, index = self.seed(), self.index()
        self.assertEqual(seed['issues'][0]['occurrence_count'], 1)
        self.assertEqual(seed['issues_at_capture'][0]['occurrence_count'], 3)
        self.assertEqual(index['files'][0]['issues'][0]['differs_from_capture'], ['last_seen_at', 'occurrence_count'])
        self.assertEqual(index['files'][0]['issues_differ_from_capture'],
                         {'depot-issue-7': ['last_seen_at', 'occurrence_count']})

    def test_identical_capture_issues_are_not_stored_twice(self):
        self.capture()
        self.build()
        self.assertNotIn('issues_at_capture', self.seed())
        self.assertEqual(self.index()['files'][0]['issues'][0]['differs_from_capture'], [])

    def test_index_records_the_issue_state_and_whether_it_precedes_the_batch(self):
        early = iso(T0 - timedelta(hours=2), '.817940', 'Z')
        self.capture(issue_created=early, runtime_occurrences=13, capture_occurrences=13)
        code, _ = self.build()
        self.assertEqual(code, 0)
        fact = self.index()['files'][0]['issues'][0]
        self.assertEqual((fact['created_at'], fact['occurrence_count']), (early, 13))
        self.assertTrue(fact['created_at_precedes_batch'])
        self.assertEqual(self.seed()['issues'][0]['created_at'], early)        # not changed

    def test_a_missing_run_time_file_stops_the_build(self):
        self.capture()
        shutil.rmtree(self.runtime)
        with self.assertRaises(bs.SeedError):
            self.build()


# What the brief asks the shift test to look for, written independently of the tool.
ISO_ANY = re.compile(r'(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})')
EPOCH_ANY = re.compile(r'(?<!\d)(\d{19}|\d{13}|\d{10})(?!\d)')


def time_looking(doc, lo, hi):
    """Paths of every ISO string or 10/13/19-digit epoch between lo and hi."""
    hits = []
    e0 = datetime(1970, 1, 1)

    def check(path, text):
        for m in ISO_ANY.finditer(text):
            if lo <= datetime(*[int(g) for g in m.groups()]) <= hi:
                hits.append((path, m.group(0)))
        for m in EPOCH_ANY.finditer(text):
            digits = m.group(1)
            when = e0 + timedelta(seconds=int(digits) / {10: 1, 13: 10 ** 3, 19: 10 ** 9}[len(digits)])
            if lo <= when <= hi:
                hits.append((path, digits))

    def rec(obj, path):
        if isinstance(obj, dict):
            for k, v in obj.items():
                check(path + '/#key', str(k))
                rec(v, path + '/' + str(k))
        elif isinstance(obj, list):
            for v in obj:
                rec(v, path + '/*')
        elif isinstance(obj, str):
            check(path, obj)
        elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
            check(path, repr(int(obj)))
    rec(doc, '')
    return hits


class TimeTest(Base):
    def test_no_time_is_shifted_in_the_file_and_the_anchor_is_the_batch_timestamp(self):
        self.capture()
        self.build()
        seed = self.seed()
        self.assertEqual(seed['anchor'], iso(BATCH_TS, '.464258', 'Z'))
        self.assertEqual(seed['investigation']['window_start'], iso(T0, '.023965'))
        self.assertEqual(seed['injection']['fault_started'], (T0 + timedelta(minutes=2)).strftime('%Y-%m-%dT%H:%M:%SZ'))

    def test_every_format_is_found_with_its_path(self):
        self.capture()
        self.build()
        paths = self.index()['time']['paths']
        self.assertEqual(paths['/anchor'], ['iso'])
        self.assertEqual(paths['/batch/batch_id'], ['compact'])
        self.assertEqual(paths['/batch/data/logs/*/_id'], ['epoch_ns_text'])
        self.assertEqual(paths['/batch/data/logs/*/_source/time'], ['epoch_ms_number'])
        self.assertEqual(paths['/batch/data/logs/*/_source/@timestamp'], ['iso'])
        self.assertEqual(paths['/batch/data/logs/*/_source/message'], ['iso'])
        self.assertEqual(paths['/batch/data/change_events/*/message'], ['epoch_s_text', 'human'])
        self.assertEqual(paths['/batch/data/metrics/cpu/*/time'], ['iso'])
        self.assertIn('/traces/items/*/spans/*/start_time', paths)
        self.assertIn('/injection/revert/at', paths)
        self.assertIn('/source/captured_at', paths)
        self.assertIn('/issues/*/created_at', paths)
        self.assertIn('/batch/data/analysis_result/correlated_issues/*/evidence_sources/metrics/*', paths)
        # A 10-digit metric value near the anchor is a figure, not a time.
        self.assertNotIn('/batch/data/metrics/cpu/*/value', paths)
        self.assertIn('/batch/analysis_text', self.index()['time']['clock_time_only_paths'])
        for formats in paths.values():
            for fmt in formats:
                self.assertIn(fmt, bs.TIME_FORMATS)

    def test_shifting_by_the_documented_paths_leaves_no_time_behind(self):
        self.capture()
        self.build()
        seed, paths = self.seed(), self.index()['time']['paths']
        lo = datetime(2026, 2, 1)
        hi = datetime(2026, 4, 20)
        before = time_looking(seed, lo, hi)
        self.assertGreater(len(before), 1000)
        delta = 400 * 86400
        moved = bs.shift_times(seed, delta, paths, seed['anchor'])
        left = [h for h in time_looking(moved, lo, hi) if not h[0].endswith('/metrics/cpu/*/value')]
        self.assertEqual(left, [])
        # ... and they all arrived, in the same form, exactly one delta later.
        after = time_looking(moved, lo + timedelta(seconds=delta), hi + timedelta(seconds=delta))
        self.assertEqual(len(after), len([h for h in before if not h[0].endswith('/metrics/cpu/*/value')]))
        shifted = BATCH_TS + timedelta(seconds=delta)
        self.assertEqual(moved['anchor'], iso(shifted, '.464258', 'Z'))
        self.assertEqual(moved['batch']['batch_id'], 'depot-batch-%s-9d63' % shifted.strftime('%Y%m%d%H%M%S'))
        first, first_moved = seed['batch']['data']['logs'][0], moved['batch']['data']['logs'][0]
        self.assertEqual(first_moved['_source']['time'], first['_source']['time'] + delta * 1000)
        self.assertIsInstance(first_moved['_source']['time'], float)
        self.assertEqual(int(first_moved['_id'].split('-')[0]), int(first['_id'].split('-')[0]) + delta * 10 ** 9)
        self.assertEqual(first_moved['_id'].split('-')[1], first['_id'].split('-')[1])
        event = moved['batch']['data']['change_events'][0]['message']
        self.assertIn((T0 + timedelta(minutes=3, seconds=delta)).strftime('%d %b %Y %H:%M:%S.419'), event)
        self.assertIn('(%d)' % (epoch(T0 + timedelta(minutes=3)) + delta), event)
        # Figures are untouched.
        self.assertEqual(moved['batch']['token_count'], seed['batch']['token_count'])
        self.assertEqual(moved['batch']['data']['metrics']['cpu'][0]['value'], 1773144000)
        self.assertEqual(moved['batch']['data']['code_changes'][0]['sha'], '4d5abd99')

    def test_shift_leaves_unlisted_paths_alone(self):
        doc = {'a': '2026-03-10T12:00:00Z', 'b': '2026-03-10T12:00:00Z'}
        moved = bs.shift_times(doc, 86400, {'/a': ['iso']}, '2026-03-10T12:00:00Z')
        self.assertEqual(moved, {'a': '2026-03-11T12:00:00Z', 'b': '2026-03-10T12:00:00Z'})

    def test_shift_keeps_each_written_form(self):
        anchor = '2026-03-10T12:00:00Z'
        doc = {'v': ['2026-03-10 23:59:59,914 x', '2026-03-10T23:59:59.914767672Z', '10 Mar 2026 23:59:59.419',
                     '2026/03/10 23:59:59 x', '10/Mar/2026:23:59:59 +0000', 'logs-2026.03.10', '1773187199'],
               'at': 1773187199, 'ms': 1773187199000, 'ns': 1773187199000000000, 'size': 1773187199,
               'by-time': {'2026-03-10T23:59:59Z': 1}}
        paths = bs.find_time_paths(doc, anchor)
        self.assertNotIn('/size', paths)
        moved = bs.shift_times(doc, 86400, paths, anchor)
        self.assertEqual(moved['v'], ['2026-03-11 23:59:59,914 x', '2026-03-11T23:59:59.914767672Z',
                                      '11 Mar 2026 23:59:59.419', '2026/03/11 23:59:59 x',
                                      '11/Mar/2026:23:59:59 +0000', 'logs-2026.03.11', '1773273599'])
        self.assertEqual((moved['at'], moved['ms'], moved['ns'], moved['size']),
                         (1773273599, 1773273599000, 1773273599000000000, 1773187199))
        self.assertEqual(list(moved['by-time']), ['2026-03-11T23:59:59Z'])


class TimeWindowTest(Base):
    def test_a_converted_capture_lies_inside_its_window(self):
        self.capture()
        self.build()
        self.assertEqual(bs.check_time_window(self.seed()), {})

    def test_a_time_outside_the_window_is_reported_by_path_only(self):
        self.capture()
        self.build()
        seed = self.seed()
        seed['batch']['data']['logs'][3]['_source']['@timestamp'] = iso(T0 - timedelta(minutes=16))
        seed['traces']['items'][0]['start_time'] = iso(BATCH_TS + timedelta(hours=1))
        bad = bs.check_time_window(seed)
        self.assertEqual(bad, {'/batch/data/logs/*/_source/@timestamp': 1, '/traces/items/*/start_time': 1})
        seed['batch']['data']['logs'][3]['_source']['@timestamp'] = iso(T0 - timedelta(minutes=14))
        self.assertEqual(list(bs.check_time_window(seed)), ['/traces/items/*/start_time'])

    def test_an_early_created_at_is_exempt_but_other_early_issue_times_are_not(self):
        early = iso(T0 - timedelta(hours=2), '.817940', 'Z')
        self.capture(issue_created=early)
        self.build()
        seed = self.seed()
        self.assertEqual(bs.check_time_window(seed), {})
        seed['issues'][0]['last_seen_at'] = early
        self.assertEqual(bs.check_time_window(seed), {'/issues/*/last_seen_at': 1})

    def test_verify_writes_violations_to_the_private_report_without_values(self):
        self.capture()
        self.build()
        path = os.path.join(self.out, '%s-%s.json.gz' % (ESTATE, TAG))
        seed = self.seed()
        late = iso(BATCH_TS + timedelta(hours=5))
        seed['batch']['data']['logs'][0]['_source']['@timestamp'] = late
        bs.write_gz(path, bs.dump_bytes(seed))
        failures, doubtful, violations = bs.verify_outputs(self.out, self.rmap)
        self.assertEqual(violations, {'%s-%s.json.gz' % (ESTATE, TAG): {'/batch/data/logs/*/_source/@timestamp': 1}})
        report = bs.write_verify_report(self.private, failures, doubtful, violations, 2)
        text = slurp(report).decode()
        self.assertIn('/batch/data/logs/*/_source/@timestamp', text)
        self.assertNotIn(late, text)


class DeterminismTest(Base):
    def test_same_inputs_and_map_give_the_same_bytes(self):
        self.capture()
        self.build()
        first = {n: slurp(os.path.join(self.out, n)) for n in sorted(os.listdir(self.out))}
        reports = {n: slurp(os.path.join(self.private, n)) for n in sorted(os.listdir(self.private))}
        shutil.rmtree(self.out)
        self.build()
        again = {n: slurp(os.path.join(self.out, n)) for n in sorted(os.listdir(self.out))}
        self.assertEqual(first, again)
        self.assertEqual(sorted(first), ['depot-Z1-r1.json.gz', 'index.json'])
        self.assertEqual(reports, {n: slurp(os.path.join(self.private, n))
                                   for n in sorted(os.listdir(self.private))})
        # No clock or file name in the gzip header.
        self.assertEqual(first['depot-Z1-r1.json.gz'][3], 0)
        self.assertEqual(first['depot-Z1-r1.json.gz'][4:8], b'\x00\x00\x00\x00')
        index = self.index()
        self.assertEqual(index['files'][0]['bytes'], len(first['depot-Z1-r1.json.gz']))


class VerifyTest(Base):
    def planted(self, mutate):
        self.capture()
        code, _ = self.build()
        self.assertEqual(code, 0)
        path = os.path.join(self.out, '%s-%s.json.gz' % (ESTATE, TAG))
        seed = self.seed()
        mutate(seed)
        bs.write_gz(path, bs.dump_bytes(seed))
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            code = bs.main(['--verify', '--rename-map', self.map_file(), '--out', self.out,
                            '--private-dir', self.private])
        return code, printed.getvalue()

    def map_file(self):
        path = os.path.join(self.root, 'rename-map.json')
        with open(path, 'wb') as f:
            f.write(bs.dump_bytes(self.rmap, pretty=True))
        return path

    def test_clean_output_passes(self):
        code, printed = self.planted(lambda seed: None)
        self.assertEqual(code, 0, printed)
        self.assertIn('0 failed checks', printed)

    def test_a_planted_real_name_fails_and_is_not_printed(self):
        def plant(seed):
            seed['batch']['data']['logs'][5]['_source']['message'] += ' pushed by %s' % AUTHOR.upper()
        code, printed = self.planted(plant)
        self.assertEqual(code, 3)
        self.assertIn('real person value from the rename map', printed)
        self.assertNotIn(AUTHOR.lower(), printed.lower())
        self.assertIn(AUTHOR, slurp(os.path.join(self.private, 'verify-report.md')).decode())

    def test_a_planted_real_host_inside_the_compressed_file_fails(self):
        def plant(seed):
            seed['traces']['items'][0]['spans'][0]['attributes']['host.name'] = NODE_B
        code, printed = self.planted(plant)
        self.assertEqual(code, 3)
        self.assertNotIn(NODE_B, printed)

    def test_a_planted_secret_fails_and_is_not_printed(self):
        secret = 'ghp_' + 'A1b2C3d4E5' * 4
        def plant(seed):
            seed['issues'][0]['description'] += ' token ' + secret
        code, printed = self.planted(plant)
        self.assertEqual(code, 3)
        self.assertIn('secret pattern: GitHub token', printed)
        self.assertNotIn(secret, printed)

    def test_the_capture_tools_pattern_list_is_the_one_used(self):
        patterns = bs.secret_patterns()
        for name in ('private key', 'kubeconfig', 'bearer token', 'JWT', 'Anthropic key', 'AWS key', 'Slack webhook'):
            self.assertIn(name, patterns)

    def test_foreign_address_mail_and_host_fail(self):
        for value, label in (('peer 8.8.8.8 down', 'IP address outside'),
                             ('ask ops@corp.test', 'e-mail address outside'),
                             ('see https://intranet.corp.test/x', 'URL host outside'),
                             ('see https://github.com/someone/else', 'URL host outside'),
                             ('see https://github.com/acme-cloud/depot', 'URL host outside'),
                             ('repository github.com/acme-cloud/depot', 'URL host outside')):
            def plant(seed, value=value):
                seed['issues'][0]['recommendation'] = value
            shutil.rmtree(self.root)
            os.makedirs(self.root)
            code, printed = self.planted(plant)
            self.assertEqual(code, 3, value)
            self.assertIn(label, printed)

    def test_in_cluster_and_placeholder_hosts_pass(self):
        def plant(seed):
            seed['issues'][0]['recommendation'] = (
                'call http://billing.depot:8080/charge or http://stock:80 or http://cache.depot.svc.cluster.local, '
                'see https://git.acme.example/acme-cloud/depot/commit/4d5abd99 and https://status.acme.example, '
                'mail ops@acme.example, peer 203.0.113.9 and 10.20.1.1')
        code, printed = self.planted(plant)
        self.assertEqual(code, 0, printed)

    def test_build_refuses_to_write_when_verification_fails(self):
        self.capture()
        del self.rmap['person'][AUTHOR]              # the map no longer covers the author: the name stays in
        self.rmap['person_alias'] = {}
        self.rmap['email'] = {}
        self.rmap['repo'] = {}
        full, _ = bs.discover(self.captures, self.runtime, self.selection)
        self.out = os.path.join(self.root, 'out')
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            real_values = bs.real_values
            bs.real_values = lambda rmap: real_values(full)          # verify with the full list
            try:
                code, _ = bs.build_all(self.captures, self.runtime, self.rmap, self.out,
                                       os.path.join(self.root, 'private'), self.selection)
            finally:
                bs.real_values = real_values
        self.assertEqual(code, 3)
        self.assertFalse(os.path.exists(self.out))
        self.assertIn('nothing written', printed.getvalue())
        self.assertNotIn(AUTHOR, printed.getvalue())

    def test_the_map_and_reports_must_live_outside_the_repository(self):
        inside = os.path.join(os.path.dirname(os.path.abspath(bs.__file__)), 'rename-map.json')
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            code = bs.main(['--verify', '--rename-map', inside])
        self.assertEqual(code, 2)
        self.assertIn('outside the repository', printed.getvalue())


class ReportTest(Base):
    def test_private_reports_are_written(self):
        self.capture()
        self.build()
        names = slurp(os.path.join(self.private, 'third-party-names.md')).decode()
        self.assertIn('| Claude (AI model) |', names)
        self.assertIn('| pip / PyPI |', names)
        self.assertIn('`4d5abd99`', names)
        self.assertIn('| no |', names)
        facts = slurp(os.path.join(self.private, 'resolution-facts.md')).decode()
        self.assertIn('## Depot Z1 r1', facts)
        self.assertIn('-n depot rollout undo deploy/stock', facts)
        self.assertIn('Lasted: 8 min 00 s (480 s)', facts)
        self.assertIn('CRITICAL, component `stock`, type DATABASE_ERROR', facts)

    def test_healthy_windows_are_not_in_the_resolution_facts(self):
        seed = {'source': {'healthy_window': True, 'incident': 'Z2', 'round': 'r1'}, 'project': {'name': 'Depot'}}
        self.assertNotIn('Z2', bs.resolution_facts([('x.json.gz', seed)]))


if __name__ == '__main__':
    unittest.main()
