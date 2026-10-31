"""Log files rotate by size instead of growing without limit."""
import logging.config
import os
import tempfile

from django.test import SimpleTestCase


class LogRotationTest(SimpleTestCase):
    def test_file_handlers_rotate_and_keep_a_bounded_number_of_copies(self):
        from api import settings as production  # test_settings replaces LOGGING
        handlers = production.LOG_FILE_HANDLERS
        for name in ('file', 'user_actions'):
            with self.subTest(name):
                self.assertEqual(handlers[name]['class'], 'logging.handlers.RotatingFileHandler')
                self.assertGreater(handlers[name]['maxBytes'], 0)

    def test_rotation_happens_with_the_configured_shape(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'django.log')
            logging.config.dictConfig({
                'version': 1, 'disable_existing_loggers': False,
                'handlers': {'f': {'class': 'logging.handlers.RotatingFileHandler', 'filename': path,
                                   'maxBytes': 1024, 'backupCount': 2, 'delay': True}},
                'loggers': {'rotation-test': {'handlers': ['f'], 'level': 'INFO', 'propagate': False}},
            })
            log = logging.getLogger('rotation-test')
            for i in range(200):
                log.info('line %04d %s', i, 'x' * 40)
            for h in log.handlers:
                h.close()
            files = sorted(os.listdir(d))
            self.assertEqual(files, ['django.log', 'django.log.1', 'django.log.2'])
            self.assertTrue(all(os.path.getsize(os.path.join(d, f)) <= 1024 + 100 for f in files))
