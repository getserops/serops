"""The benchmark's own rules: scenario integrity, scoring, and the runner
with the AI call replaced (no cost)."""
import uuid
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, TestCase

from rca_benchmark import report, runner
from rca_benchmark.dataset import answer
from rca_benchmark.scoring import names_service, primary, score, sequence_checks, severity_between


def issue(component='checkout-api', severity='CRITICAL', confidence='HIGH', root_cause='', description='',
          recommendation='', linked_commits=None, affected_services=None):
    return {'component': component, 'severity': severity, 'confidence': confidence, 'root_cause': root_cause,
            'description': description, 'recommendation': recommendation, 'linked_commits': linked_commits,
            'affected_services': affected_services or []}


class ScenarioIntegrityTest(SimpleTestCase):
    def test_every_scenario_is_well_formed(self):
        builds = runner.select()
        ids = [b.__name__ for b in builds]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(runner.SETS['held_out']), 9)
        for b in builds:
            sc = b()
            a = sc['answer']
            with self.subTest(sc['id']):
                self.assertEqual(sc['id'], b.__name__)
                self.assertIn(sc['set'], runner.SETS)
                self.assertTrue(a['services'])
                if a['benign_max'] is None:
                    self.assertTrue(a['cause'], 'an incident needs cause words')
                shas = {c['sha'] for c in sc['data'].get('code_changes') or []}
                if a['blame_sha']:
                    self.assertIn(a['blame_sha'], shas)
                self.assertLessEqual(set(a['wrong_shas']), shas)


class HeldOutV2IntegrityTest(SimpleTestCase):
    def test_v2_set_is_well_formed_and_opt_in(self):
        builds = runner.select(['held_out_v2'])
        self.assertEqual(len(builds), 32)  # v29 moved to the tuned set on 2026-11-16
        self.assertNotIn(builds[0], runner.select())  # not in the default run
        healthy = 0
        for b in builds:
            sc = b()
            a = sc['answer']
            with self.subTest(sc['id']):
                self.assertEqual((sc['id'], sc['set']), (b.__name__, 'held_out_v2'))
                shas = {c['sha'] for c in sc['data'].get('code_changes') or []}
                if a['blame_sha']:
                    self.assertIn(a['blame_sha'], shas)
                self.assertLessEqual(set(a['wrong_shas']), shas)
                healthy += a['benign_max'] is not None
                if a['benign_max'] is None:
                    self.assertTrue(a['cause'])
        self.assertEqual(healthy, 2)
        self.assertIn('v29_healthy_deploy_warmup', [b().get('id') for b in runner.select(['tuned_v3'])])


class HeldOutV3IntegrityTest(SimpleTestCase):
    def test_v3_set_is_well_formed_and_opt_in(self):
        moved = {19, 36, 37, 38, 39, 40}  # to the tuned set on 2026-11-16 (MR !121 was shaped on them)
        builds = runner.select(['held_out_v3'])
        self.assertEqual(len(builds), 40 - len(moved))
        self.assertEqual([b.__name__[:3] for b in builds], [f'w{n:02d}' for n in range(1, 41) if n not in moved])
        tuned_ids = [b().get('id') for b in runner.select(['tuned_v3'])]
        for n in moved:
            self.assertTrue(any(i.startswith(f'w{n:02d}_') for i in tuned_ids), n)
        builds = builds + [b for b in runner.select(['tuned_v3']) if b.__name__.startswith('w')]
        self.assertNotIn(builds[0], runner.select())  # not in the default run
        healthy = sequences = 0
        for b in builds:
            sc = b()
            with self.subTest(sc['id']):
                self.assertEqual((sc['id'], sc['set']),
                                 (b.__name__, 'tuned' if int(b.__name__[1:3]) in moved else 'held_out_v3'))
                windows = sc.get('batches') or [{'data': sc['data'], 'answer': sc['answer']}]
                if 'batches' in sc:
                    sequences += 1
                    self.assertTrue(3 <= len(windows) <= 6)
                    self.assertTrue(sc['sequence']['services'])
                    self.assertIsNotNone(windows[-1]['answer']['benign_max'], 'the last window is the recovery')
                    self.assertIsNone(windows[0]['answer']['benign_max'], 'the first window is the incident')
                elif sc['answer']['benign_max'] is not None and sc['category'] == 'healthy':
                    healthy += 1
                for w in windows:
                    a = w['answer']
                    shas = {c['sha'] for c in w['data'].get('code_changes') or []}
                    if a['blame_sha']:
                        self.assertIn(a['blame_sha'], shas)
                    self.assertLessEqual(set(a['wrong_shas']), shas)
                    if a['benign_max'] is None:
                        self.assertTrue(a['cause'])
                    for low, high in [w['severity']] if w.get('severity') else []:
                        self.assertIn(low, ('INFO', 'WARNING', 'CRITICAL'))
                        self.assertIn(high, ('INFO', 'WARNING', 'CRITICAL'))
        self.assertEqual((healthy, sequences), (6, 5))


class ScoringTest(SimpleTestCase):
    key = answer(['checkout-api'], cause=[['pool'], ['5', 'shrunk']], blame_sha='a91f3c27', wrong_shas=['c03be19d'])

    def test_correct_top_issue_passes(self):
        r = score(self.key, [issue(root_cause='DB pool shrunk to 5 in a91f3c27', linked_commits=['a91f3c27'])])
        self.assertTrue(r['root_cause'])
        self.assertTrue(r['verdict'])

    def test_right_answer_on_a_lesser_issue_is_not_root_cause(self):
        issues = [issue(component='payments', root_cause='payment provider slow'),
                  issue(component='checkout-api', severity='WARNING', root_cause='pool shrunk to 5',
                        linked_commits=['a91f3c27'])]
        r = score(self.key, issues)
        self.assertFalse(r['root_cause'])
        self.assertTrue(r['lenient'])

    def test_confidence_breaks_severity_ties(self):
        low = issue(component='a', confidence='LOW')
        high = issue(component='b', confidence='HIGH')
        self.assertIs(primary([low, high]), high)

    def test_blaming_a_distractor_fails_all_checks_not_root_cause(self):
        r = score(self.key, [issue(root_cause='pool shrunk to 5', linked_commits=['a91f3c27', 'c03be19d'])])
        self.assertTrue(r['root_cause'])
        self.assertFalse(r['verdict'])

    def test_missing_commit_fails_root_cause(self):
        self.assertFalse(score(self.key, [issue(root_cause='pool shrunk to 5')])['root_cause'])

    def test_too_many_issues_is_not_focused(self):
        r = score(self.key, [issue(root_cause='pool shrunk to 5', linked_commits=['a91f3c27'])] * 3)
        self.assertFalse(r['checks']['focused'])

    def test_whole_service_names(self):
        self.assertFalse(names_service('redis-cache', ['redis']))
        self.assertTrue(names_service('redis-cache', ['redis-cache']))
        self.assertTrue(names_service('the coredns pods', ['coredns']))
        self.assertTrue(names_service('orders-api', ['orders-api.prod.svc.cluster.local']))

    def test_affected_services_count_for_the_top_issue(self):
        key = answer(['redis-cache'], cause=[['maxclients']])
        r = score(key, [issue(component='cart-api', affected_services=['redis-cache'], root_cause='maxclients 200')])
        self.assertTrue(r['root_cause'])

    def test_healthy_window(self):
        key = answer(['search'], benign_max='WARNING')
        self.assertTrue(score(key, [issue(severity='WARNING')])['verdict'])
        self.assertFalse(score(key, [issue(severity='CRITICAL')])['verdict'])
        self.assertTrue(score(key, [])['verdict'])

    def test_critical_on_a_decoy_fails(self):
        key = answer(['notifications-svc'], cause=[['smtp']], decoy_services=['mobile-gateway'])
        issues = [issue(component='notifications-svc', root_cause='smtp credentials rotated'),
                  issue(component='mobile-gateway', root_cause='404s')]
        r = score(key, issues)
        self.assertTrue(r['root_cause'])
        self.assertFalse(r['checks']['no critical on mobile-gateway'])

    def test_second_cause_must_be_named_by_some_alerting_issue(self):
        key = answer(['planner'], cause=[['null']], max_issues=3,
                     also=[{'services': ['elasticsearch'], 'cause': [['disk']]}])
        top = issue(component='planner', root_cause='null postcode')
        self.assertFalse(score(key, [top])['verdict'])
        self.assertTrue(score(key, [top])['root_cause'])
        second = issue(component='elasticsearch', severity='WARNING', root_cause='disk watermark exceeded')
        self.assertTrue(score(key, [top, second])['verdict'])
        info = issue(component='elasticsearch', severity='INFO', root_cause='disk watermark exceeded')
        self.assertFalse(score(key, [top, info])['verdict'])

    def test_forbidden_text_anywhere_fails(self):
        key = answer(['payment-svc'], cause=[['vault']], forbidden_text=['jane@example.org'])
        clean = issue(component='payment-svc', root_cause='vault path renamed')
        self.assertTrue(score(key, [clean])['verdict'])
        leaky = issue(component='payment-svc', root_cause='vault path renamed', recommendation='mail Jane@example.org')
        r = score(key, [leaky])
        self.assertFalse(r['verdict'])
        self.assertTrue(r['root_cause'])

    def test_severity_bounds_of_a_window(self):
        self.assertTrue(severity_between([issue(severity='CRITICAL')], 'CRITICAL', 'CRITICAL'))
        self.assertFalse(severity_between([issue(severity='WARNING')], 'CRITICAL', 'CRITICAL'))
        self.assertTrue(severity_between([], 'INFO', 'WARNING'))  # quiet meets an INFO floor
        self.assertFalse(severity_between([], 'WARNING', 'CRITICAL'))
        self.assertFalse(severity_between([issue(severity='CRITICAL')], 'INFO', 'WARNING'))

    def test_a_continuing_incident_reuses_its_issue(self):
        seq = {'services': ['events-api'], 'max_distinct': 1}
        same = [[dict(issue(component='events-api'), id=7)], [dict(issue(component='events-api'), id=7)], []]
        new_each_time = [[dict(issue(component='events-api'), id=7)], [dict(issue(component='events-api'), id=8)]]
        other = [[dict(issue(component='events-api'), id=7)], [dict(issue(component='web'), id=9)]]
        info_only = [[dict(issue(component='events-api'), id=7)], [dict(issue(component='events-api', severity='INFO'), id=8)]]
        check = lambda w: all(sequence_checks(seq, w).values())  # noqa: E731
        self.assertTrue(check(same))
        self.assertFalse(check(new_each_time))
        self.assertTrue(check(other))
        self.assertTrue(check(info_only))

    def test_no_issue_is_not_detected(self):
        r = score(self.key, [issue(severity='INFO', root_cause='pool shrunk to 5')])
        self.assertFalse(r['checks']['detected'])


class RunnerTest(TestCase):
    """analyze_batch replaced: creates the issue a scenario expects (or not)."""

    def fake_analysis(self, correct):
        from ai_model.models import AITokenUsage
        from Data.models import AIAnalyzedBatch, Issue, IssueOccurrence

        def analyse(batch_id):
            batch = AIAnalyzedBatch.objects.get(batch_id=batch_id)
            batch.model_name = 'fake-model'
            batch.save(update_fields=['model_name'])
            AITokenUsage.objects.create(organisation=batch.organisation, batch=batch, model_name='fake-model',
                                        tokens_input=100, tokens_output=50, tokens_total=150,
                                        cost_usd=Decimal('0.01'))
            sid = batch_id[len('rca-bench-'):-9]
            sc = next(b for b in runner.select() if b.__name__ == sid)()
            a = sc['answer']
            if a['benign_max'] or not correct:
                return
            words = ' '.join(g[0] for g in a['cause'])
            i = Issue.objects.create(batch=batch, project=batch.project, organisation=batch.organisation,
                                     severity='CRITICAL', confidence='HIGH', component=a['services'][0],
                                     description=words, root_cause=f"{words} {a['blame_sha'] or ''}",
                                     fingerprint=uuid.uuid4().hex,
                                     linked_commits=[a['blame_sha']] if a['blame_sha'] else [])
            IssueOccurrence.objects.create(issue=i, batch=batch)
        return analyse

    def test_scores_and_cleans_up(self):
        from Organisations.models import Organisations
        builds = runner.select(only=['h01', 'h09', 's10'])
        with mock.patch('ai_model.tasks.analyze_batch', side_effect=self.fake_analysis(True)):
            results, stopped = runner.run(builds, 'gemini', 'key', budget_usd=1)
        self.assertIsNone(stopped)
        self.assertEqual([r['id'] for r in results], ['h01_connection_leak', 'h09_benign_deploy',
                                                      's10_redis_maxclients'])
        self.assertTrue(all(r['score']['verdict'] for r in results), [r['score'] for r in results])
        self.assertEqual(results[0]['cost_usd'], 0.01)
        self.assertFalse(Organisations.objects.filter(name__startswith='RCA Benchmark').exists())
        md = report.markdown(results, {'provider': 'gemini', 'model': 'fake-model', 'version': 'x', 'commit': 'y',
                                       'date': 'today', 'rounds': 1})
        self.assertIn('2/2 (100%)', md)
        self.assertIn('Nothing failed.', md)

    def test_wrong_answers_are_reported(self):
        builds = runner.select(only=['h01'])
        with mock.patch('ai_model.tasks.analyze_batch', side_effect=self.fake_analysis(False)):
            results, _ = runner.run(builds, 'gemini', 'key', budget_usd=1)
        self.assertFalse(results[0]['score']['root_cause'])
        md = report.markdown(results, {'provider': 'gemini', 'model': 'm', 'version': 'x', 'commit': 'y',
                                       'date': 'today', 'rounds': 1})
        self.assertIn('no issue created', md)

    def test_budget_stops_the_run(self):
        builds = runner.select(only=['h01', 'h02', 'h03'])
        with mock.patch('ai_model.tasks.analyze_batch', side_effect=self.fake_analysis(True)):
            results, stopped = runner.run(builds, 'gemini', 'key', budget_usd=0.015)
        self.assertEqual(len(results), 2)
        self.assertIn('budget reached', stopped)


    def test_a_refused_account_stops_the_run(self):
        from Data.models import AIAnalyzedBatch

        def refused(batch_id):
            AIAnalyzedBatch.objects.filter(batch_id=batch_id).update(model_name='FAILED (SPEND_LIMIT)')
        builds = runner.select(only=['h01', 'h02', 'h03'])
        with mock.patch('ai_model.tasks.analyze_batch', side_effect=refused), mock.patch('time.sleep'):
            results, stopped = runner.run(builds, 'gemini', 'key', budget_usd=1)
        self.assertEqual(len(results), 1)
        self.assertIn('SPEND_LIMIT', stopped)

    def test_model_and_ablation(self):
        from Data.models import AIAnalyzedBatch
        from org_settings.models import AIModelProvider
        seen = {}

        def analyse(batch_id):
            seen[batch_id] = dict(AIAnalyzedBatch.objects.get(batch_id=batch_id).data)
        builds = runner.select(sets=['held_out_v2'], only=['v01', 'v25'])
        with mock.patch('ai_model.tasks.analyze_batch', side_effect=analyse):
            results, _ = runner.run(builds, 'gemini', 'key', budget_usd=1, retries=0,
                                    model='gemini-test-model', drop=['code'])
        self.assertEqual(AIModelProvider.objects.get(name='gemini').default_model, 'gemini-test-model')
        self.assertTrue(seen)
        self.assertTrue(all('code_changes' not in data for data in seen.values()))
        self.assertTrue(all(r['dropped'] == ['code'] for r in results))
        with_code = [b for b in builds if 'code_changes' in b()['data']]
        self.assertEqual(len(results), len(with_code))  # a scenario without code is skipped


class SequenceRunnerTest(TestCase):
    """A multi-window incident runs in order on one project; issues carry over."""

    def test_windows_share_a_project_and_are_scored_together(self):
        from Data.models import AIAnalyzedBatch, Issue, IssueOccurrence
        projects, batches = set(), []

        def analyse(batch_id):
            batch = AIAnalyzedBatch.objects.get(batch_id=batch_id)
            projects.add(batch.project_id)
            batches.append(batch_id)
            batch.model_name = 'fake-model'
            batch.save(update_fields=['model_name'])
            if len(batches) > 2:  # the incident is over: nothing raised
                return
            existing = Issue.objects.filter(project=batch.project).first()
            i = existing or Issue.objects.create(
                batch=batch, project=batch.project, organisation=batch.organisation, severity='CRITICAL',
                confidence='HIGH', component='events-api', description='memory leak, heap grows (buffer)',
                root_cause='memory oom leak heap a2b4c6d', fingerprint=uuid.uuid4().hex, linked_commits=['a2b4c6d8'])
            IssueOccurrence.objects.create(issue=i, batch=batch)
        builds = runner.select(['tuned_v3'], only=['w36'])
        with mock.patch('ai_model.tasks.analyze_batch', side_effect=analyse):
            results, stopped = runner.run(builds, 'gemini', 'key', budget_usd=1, retries=0)
        self.assertIsNone(stopped)
        self.assertEqual(len(projects), 1)
        self.assertEqual([r['id'] for r in results], [f'w36_seq_leak_to_rollback#{n}' for n in range(1, 5)])
        self.assertTrue(all(r['sequence'] == 'w36_seq_leak_to_rollback' for r in results))
        self.assertTrue(all(r['score']['verdict'] for r in results), [r['score']['checks'] for r in results])
        self.assertIn('one issue across windows (≤1)', results[-1]['score']['checks'])
        s = report.summarise(results)
        self.assertEqual(s['sequences'], {'runs': 1, 'passed': 1})
        md = report.markdown(results, {'provider': 'gemini', 'model': 'm', 'version': 'x', 'commit': 'y',
                                       'date': 'today', 'rounds': 1})
        self.assertIn('every window: 1/1 (100%)', md)

    def test_a_new_issue_each_window_fails_the_sequence(self):
        from Data.models import AIAnalyzedBatch, Issue, IssueOccurrence
        count = []

        def analyse(batch_id):
            batch = AIAnalyzedBatch.objects.get(batch_id=batch_id)
            count.append(batch_id)
            if len(count) > 2:
                return
            i = Issue.objects.create(batch=batch, project=batch.project, organisation=batch.organisation,
                                     severity='CRITICAL', confidence='HIGH', component='events-api',
                                     description='memory leak heap grows', root_cause='memory oom leak a2b4c6d',
                                     fingerprint=uuid.uuid4().hex, linked_commits=['a2b4c6d8'])
            IssueOccurrence.objects.create(issue=i, batch=batch)
        builds = runner.select(['tuned_v3'], only=['w36'])
        with mock.patch('ai_model.tasks.analyze_batch', side_effect=analyse):
            results, _ = runner.run(builds, 'gemini', 'key', budget_usd=1, retries=0)
        self.assertFalse(results[-1]['score']['checks']['one issue across windows (≤1)'])
        self.assertEqual(report.summarise(results)['sequences'], {'runs': 1, 'passed': 0})


class SummaryTest(SimpleTestCase):
    def test_runs_without_analysis_are_left_out_of_accuracy(self):
        key = answer(['a'], cause=[['x']])
        ok = {'set': 'held_out', 'answer': key, 'error': None, 'cost_usd': 0, 'seconds': 1, 'id': 'h1',
              'score': score(key, [issue(component='a', root_cause='x')])}
        failed = dict(ok, id='h2', error='FAILED (QUOTA_EXCEEDED)', score=None)
        s = report.summarise([ok, failed])['held_out']
        self.assertEqual((s['root_cause'], s['incidents'], s['errors']), (1, 1, 1))
