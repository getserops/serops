"""A line naming an exception counts as an error whatever its level field
says (phase 3 client C3: a crash loop tagged INFO looked healthy)."""
from datetime import datetime, timezone

from django.test import SimpleTestCase

from Data.log_filters import is_important_log
from integrations.schemas import LogEntry


def entry(message, level='INFO'):
    return LogEntry(timestamp=datetime.now(timezone.utc), message=message, level=level)


class ExceptionLinesTest(SimpleTestCase):
    def test_python_exception_tagged_info(self):
        self.assertTrue(is_important_log(entry('ValueError: Port out of range 0-65535')))

    def test_java_exception(self):
        self.assertTrue(is_important_log(entry('java.lang.IllegalStateException: pool closed')))

    def test_js_type_error(self):
        self.assertTrue(is_important_log(entry("TypeError: Cannot read properties of undefined")))

    def test_legacy_dict_shape(self):
        self.assertTrue(is_important_log({'_source': {'message': 'KeyError: customer_id', 'level': 'INFO'}}))

    def test_plain_info_is_not(self):
        self.assertFalse(is_important_log(entry('served GET /health in 3ms')))
        self.assertFalse(is_important_log(entry('retry policy: ErrorBudget at 99.9%')))
        self.assertFalse(is_important_log(entry('loaded handler for ValidationError responses')))
