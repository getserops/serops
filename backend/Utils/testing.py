"""Shared test base classes.

``SeedPreservingTransactionTestCase`` exists because Django's
``TransactionTestCase`` flushes *every* table after each test, and a flush
does not put back rows that data migrations inserted — the
``AIModelProvider`` catalogue that ``org_settings`` migrations seed is the
one that bites. Inside a single run that is harmless: Django orders every
``TransactionTestCase`` after the ``TestCase`` suites, so nothing that needs
the catalogue runs after the flush.

``--keepdb`` turns it into a cross-run failure. The flushed database *is*
the database the next run starts from, and migrations do not re-run data
migrations they have already recorded as applied. The first run passes and
every later one fails somewhere unrelated — ``Organisations`` onboarding
tests asking for the ``ollama`` provider, for instance. Earlier fixes had
individual tests re-seed what they needed, which treats each symptom as it
surfaces and leaves the next test that trusts migration data to find the
same hole.

Django's own ``serialized_rollback`` does not cover this: it restores the
snapshot at the *start* of each transactional test, so the final test still
leaves the database flushed, which is exactly the state ``--keepdb`` keeps.

So this class snapshots the database the first time any transactional test
sets up — before anything in the run has flushed it, since ``TestCase``
suites roll back — and restores that snapshot after every flush. The
database ends each test, and therefore the run, as it began.
"""

from django.core.management import call_command
from django.db import connections
from django.test import TransactionTestCase


class SeedPreservingTransactionTestCase(TransactionTestCase):
    """``TransactionTestCase`` that leaves migration seed data in place.

    Flushes with CASCADE, so leftovers from a test that died mid-transaction
    cannot block the flush on a foreign key, then reloads the snapshot taken
    before the run's first flush.
    """

    # alias -> serialized contents, shared across every subclass in the run.
    _seed_snapshots: dict = {}

    def _fixture_setup(self):
        for alias in self._databases_names(include_mirrors=False):
            if alias not in SeedPreservingTransactionTestCase._seed_snapshots:
                SeedPreservingTransactionTestCase._seed_snapshots[alias] = (
                    connections[alias].creation.serialize_db_to_string()
                )
        super()._fixture_setup()

    def _fixture_teardown(self):
        for alias in self._databases_names(include_mirrors=False):
            connection = connections[alias]
            connection.close()
            connection.ensure_connection()
            call_command(
                'flush', verbosity=0, interactive=False, database=alias,
                reset_sequences=False, allow_cascade=True,
                inhibit_post_migrate=True,
            )
            snapshot = SeedPreservingTransactionTestCase._seed_snapshots.get(alias)
            if snapshot:
                connection.creation.deserialize_db_from_string(snapshot)
