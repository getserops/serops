"""1.5.6: create_superadmin applies the sign-up form's password rule.

Before 1.5.6 the command accepted any 8 characters, while the form asks for
10 characters with an upper-case letter, a lower-case letter and a number.
"""
import os
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from Users.models import User

GOOD = 'Tr4ns-Lunar-Gate'          # 16 chars, upper, lower, number
WEAK = [
    'abcdefgh',                    # 8 characters: the old minimum
    'Abcdefgh1',                   # 9 characters
    'abcdefgh12',                  # no upper case
    'ABCDEFGH12',                  # no lower case
    'Abcdefghij',                  # no number
    'Password123',                 # passes the shape, but a common password
]


class CreateSuperadminPasswordTest(TestCase):

    def _run(self, email, **kw):
        return call_command('create_superadmin', email=email, org='acme-cloud', stdout=StringIO(), **kw)

    def test_weak_passwords_refused_as_argument(self):
        for i, pw in enumerate(WEAK):
            with self.assertRaises(CommandError, msg=pw):
                self._run(f'a{i}@example.com', password=pw)
        self.assertFalse(User.objects.filter(email__endswith='@example.com').exists())

    def test_weak_password_refused_from_environment(self):
        with patch.dict(os.environ, {'ADMIN_PASSWORD': 'abcdefgh'}):
            with self.assertRaises(CommandError):
                self._run('env@example.com')
        self.assertFalse(User.objects.filter(email='env@example.com').exists())

    def test_weak_password_refused_at_the_prompt(self):
        with patch.dict(os.environ, {}, clear=False), \
             patch('getpass.getpass', side_effect=['abcdefgh', 'abcdefgh']):
            os.environ.pop('ADMIN_PASSWORD', None)
            with self.assertRaises(CommandError):
                self._run('prompt@example.com')
        self.assertFalse(User.objects.filter(email='prompt@example.com').exists())

    def test_message_names_the_rule(self):
        with self.assertRaises(CommandError) as ctx:
            self._run('msg@example.com', password='abcdefgh')
        self.assertIn('at least 10 characters', str(ctx.exception))

    def test_good_password_creates_the_admin(self):
        self._run('ok@example.com', password=GOOD)
        user = User.objects.get(email='ok@example.com')
        self.assertTrue(user.check_password(GOOD))
        self.assertEqual(user.role, 'admin')

    def test_good_password_from_environment_and_prompt(self):
        with patch.dict(os.environ, {'ADMIN_PASSWORD': GOOD}):
            self._run('env-ok@example.com')
        os.environ.pop('ADMIN_PASSWORD', None)
        with patch('getpass.getpass', side_effect=[GOOD, GOOD]):
            self._run('prompt-ok@example.com')
        self.assertEqual(User.objects.filter(email__in=['env-ok@example.com', 'prompt-ok@example.com']).count(), 2)
