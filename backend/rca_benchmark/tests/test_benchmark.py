"""The benchmark's own rules: scenario integrity, scoring, and the runner
with the AI call replaced (no cost)."""
import uuid
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, TestCase

from rca_benchmark import report, runner
from rca_benchmark.dataset import answer
from rca_benchmark.scoring import names_service, primary, score


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


class SummaryTest(SimpleTestCase):
    def test_runs_without_analysis_are_left_out_of_accuracy(self):
        key = answer(['a'], cause=[['x']])
        ok = {'set': 'held_out', 'answer': key, 'error': None, 'cost_usd': 0, 'seconds': 1, 'id': 'h1',
              'score': score(key, [issue(component='a', root_cause='x')])}
        failed = dict(ok, id='h2', error='FAILED (QUOTA_EXCEEDED)', score=None)
        s = report.summarise([ok, failed])['held_out']
        self.assertEqual((s['root_cause'], s['incidents'], s['errors']), (1, 1, 1))
