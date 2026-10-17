"""OTLP enum parsing: names and the integer values the JSON encoding uses."""
from django.test import SimpleTestCase

from traces.otlp_parsing import parse_kind, parse_status


class ParseStatusTest(SimpleTestCase):

    def test_integer_codes(self):
        # OTLP/HTTP JSON encodes enums as integers: 0 UNSET, 1 OK, 2 ERROR.
        self.assertEqual(parse_status({'code': 2, 'message': 'boom'}), ('ERROR', 'boom'))
        self.assertEqual(parse_status({'code': 1})[0], 'OK')
        self.assertEqual(parse_status({'code': 0})[0], 'UNSET')
        self.assertEqual(parse_status({'code': '2'})[0], 'ERROR')

    def test_names(self):
        self.assertEqual(parse_status({'code': 'STATUS_CODE_ERROR'})[0], 'ERROR')
        self.assertEqual(parse_status({'code': 'ok'})[0], 'OK')
        self.assertEqual(parse_status({})[0], 'UNSET')
        self.assertEqual(parse_status(None)[0], 'UNSET')


class ParseKindTest(SimpleTestCase):

    def test_integer_kinds(self):
        self.assertEqual(parse_kind(2), 'SERVER')
        self.assertEqual(parse_kind(3), 'CLIENT')
        self.assertEqual(parse_kind(4), 'PRODUCER')
        self.assertEqual(parse_kind(5), 'CONSUMER')
        self.assertEqual(parse_kind(1), 'INTERNAL')
        self.assertEqual(parse_kind(0), 'INTERNAL')

    def test_names(self):
        self.assertEqual(parse_kind('SPAN_KIND_CLIENT'), 'CLIENT')
        self.assertEqual(parse_kind('server'), 'SERVER')
        self.assertEqual(parse_kind(None), 'INTERNAL')
