"""An ELK estate with its own short field names (phase 3 client C3):
``svc``, ``lvl`` and the message in ``log`` (Fluent Bit tail input)."""
from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from integrations.schemas import LogEntry, LogQuery


class InHouseFieldNamesTest(SimpleTestCase):
    def test_record_with_short_names_parses(self):
        e = LogEntry.from_record({'@timestamp': '2026-11-16T17:00:00Z', 'log': 'route failed',
                                  'lvl': 'error', 'svc': 'dispatch'})
        self.assertEqual(e.level, 'ERROR')
        self.assertEqual(e.service, 'dispatch')
        self.assertEqual(e.message, 'route failed')

    def test_python_levelname(self):
        self.assertEqual(LogEntry.from_record({'message': 'x', 'levelname': 'WARNING'}).level, 'WARN')

    def test_error_query_reads_short_level_and_every_message_field(self):
        now = datetime.now(timezone.utc)
        dsl = LogQuery(time_range=(now - timedelta(minutes=5), now), severity=['ERROR']).to_es_dsl()
        text = repr(dsl)
        self.assertIn("'lvl'", text)
        self.assertIn("'log'", text)
        self.assertIn("'msg'", text)
