"""
/api/client-config/: usage counting is off unless the operator sets it, and
only a same-origin script path is ever handed to the browser.
"""
from django.test import TestCase, override_settings

from api.client_config import usage_config

ID = '1A7EBE10-2af1-4cd1-9112-0cd037c77b70'


class ClientConfigTests(TestCase):
    def test_off_by_default(self):
        self.assertIsNone(usage_config())
        self.assertEqual(self.client.get('/api/client-config/').json(), {'usage': None})

    @override_settings(SEROPS_USAGE_SCRIPT_PATH='/_stats/script.js', SEROPS_USAGE_WEBSITE_ID=ID)
    def test_on_when_both_are_set(self):
        res = self.client.get('/api/client-config/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {'usage': {'script_path': '/_stats/script.js', 'website_id': ID.lower()}})

    def test_one_without_the_other_is_off(self):
        with override_settings(SEROPS_USAGE_SCRIPT_PATH='/_stats/script.js', SEROPS_USAGE_WEBSITE_ID=''):
            self.assertIsNone(usage_config())
        with override_settings(SEROPS_USAGE_SCRIPT_PATH='', SEROPS_USAGE_WEBSITE_ID=ID):
            self.assertIsNone(usage_config())

    def test_only_a_same_origin_script_path(self):
        for path in ('https://stats.example.com/script.js', '//stats.example.com/script.js', 'script.js',
                     '/_stats/../x.js', '/_stats/script.js?x=1', '/a b.js', '/_stats/script', "/x'.js"):
            with override_settings(SEROPS_USAGE_SCRIPT_PATH=path, SEROPS_USAGE_WEBSITE_ID=ID):
                self.assertIsNone(usage_config(), path)

    def test_website_id_must_be_a_uuid(self):
        with override_settings(SEROPS_USAGE_SCRIPT_PATH='/_stats/script.js', SEROPS_USAGE_WEBSITE_ID='"><script>'):
            self.assertIsNone(usage_config())
