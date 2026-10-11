"""Migration seed data must survive transactional tests.

Django runs every TransactionTestCase after the TestCase suites, and module
order puts this one after Data's dedup and race-condition suites — so by the
time it runs, those have flushed the database several times. If the snapshot
restore in SeedPreservingTransactionTestCase is lost, this is where it shows,
in the same run, rather than as unrelated failures on the next --keepdb run.
"""

from org_settings.models import AIModelProvider
from Utils.testing import SeedPreservingTransactionTestCase

# Seeded by org_settings data migrations; never created by any test fixture.
MIGRATION_SEEDED_PROVIDERS = {'claude', 'gemini', 'openai', 'deepseek', 'ollama'}

RECOVERY_HINT = (
    "The AIModelProvider catalogue seeded by org_settings migrations is "
    "missing. If this test database was kept (--keepdb) from a run before "
    "SeedPreservingTransactionTestCase existed, it was already flushed: "
    "recreate it once with `manage.py test --noinput` (no --keepdb)."
)


class MigrationSeedSurvivesFlushTest(SeedPreservingTransactionTestCase):

    def test_catalogue_present_before_this_test(self):
        names = set(AIModelProvider.objects.values_list('name', flat=True))
        self.assertTrue(MIGRATION_SEEDED_PROVIDERS <= names, RECOVERY_HINT)

    def test_rows_a_test_creates_do_not_outlive_it(self):
        # The restore must bring back the seed, not keep this test's writes.
        AIModelProvider.objects.create(
            name='flush-probe', display_name='Flush probe',
            default_model='probe-1', is_active=False,
        )
        self.assertTrue(AIModelProvider.objects.filter(name='flush-probe').exists())

    def test_zz_probe_row_was_flushed(self):
        # Runs after the test above (alphabetical order within the class).
        self.assertFalse(AIModelProvider.objects.filter(name='flush-probe').exists())
        names = set(AIModelProvider.objects.values_list('name', flat=True))
        self.assertTrue(MIGRATION_SEEDED_PROVIDERS <= names, RECOVERY_HINT)
