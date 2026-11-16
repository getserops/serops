"""
A batch's prompt only gets its own environment's logs, whatever path built the
batch (held-out v3 w19: a production window whose only errors came from
staging pods blamed the staging commit, every model, 2026-11-16).
"""
from types import SimpleNamespace

from django.test import TestCase

from ai_model.tasks import _logs_for_batch_environment
from Organisations.models import Organisations
from Projects.models import Project, ProjectEnvironment


def log(env=None, msg='boom'):
    src = {'message': msg, 'log_level': 'ERROR', 'service': {'name': 'checkout-api'}}
    if env is not None:
        src['environment'] = env
    return {'_id': msg, '_source': src}


class BatchEnvironmentLogsTest(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Env Org')
        self.project = Project.objects.create(name='checkout', organisation=self.org)

    def batch(self, environment):
        return SimpleNamespace(environment=environment, project_id=self.project.pk)

    def test_other_environment_left_out(self):
        logs = [log('staging', 'stg'), log('production', 'prd'), log(None, 'untagged')]
        kept, dropped = _logs_for_batch_environment(logs, self.batch('production'))
        self.assertEqual([l['_id'] for l in kept], ['prd', 'untagged'])
        self.assertEqual(dropped, 1)

    def test_usual_spellings_and_project_labels_count(self):
        ProjectEnvironment.objects.filter(project=self.project, name='production').update(log_label_value='live')
        if not ProjectEnvironment.objects.filter(project=self.project, name='production').exists():
            ProjectEnvironment.objects.create(project=self.project, name='production', log_label_value='live')
        logs = [log('prod', 'a'), log('live', 'b'), log('stg', 'c')]
        kept, dropped = _logs_for_batch_environment(logs, self.batch('production'))
        self.assertEqual([l['_id'] for l in kept], ['a', 'b'])
        self.assertEqual(dropped, 1)

    def test_no_batch_environment_keeps_everything(self):
        logs = [log('staging', 'stg'), log('production', 'prd')]
        kept, dropped = _logs_for_batch_environment(logs, self.batch(''))
        self.assertEqual(len(kept), 2)
        self.assertEqual(dropped, 0)
