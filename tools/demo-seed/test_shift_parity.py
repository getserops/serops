#!/usr/bin/env python3
"""The backend's copy of the time code is the converter's.

``seed_demo_org`` shifts the seed files with
``backend/Data/demo_seed_time.py``: the converter is not shipped with the
backend, so its time section is copied there. The two must stay the same
code, or the loader moves times the converter did not list (or misses some).
"""

import importlib.util
import inspect
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_seed as bs  # noqa: E402

BACKEND_COPY = os.path.join(HERE, '..', '..', 'backend', 'Data', 'demo_seed_time.py')

SHARED = ('MONTHS', 'RX_ISO', 'RX_HUMAN', 'RX_SLASH', 'RX_CLF', 'RX_COMPACT', 'RX_DATE', 'RX_DIGITS', 'RX_CLOCK',
          'RX_TIME_KEY', 'EPOCH_UNITS', 'TIME_FORMATS')
SHARED_CODE = ('parse_time', '_naive', 'TimeContext', '_dt', '_string_times', '_number_time', '_esc', 'walk_times',
               'find_time_paths', 'find_clock_paths', 'shift_times')


def load_backend_copy():
    spec = importlib.util.spec_from_file_location('demo_seed_time', BACKEND_COPY)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # inspect.getsource finds a class through it
    spec.loader.exec_module(module)
    return module


class ShiftParityTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.copy = load_backend_copy()

    def test_constants_are_the_same(self):
        for name in SHARED:
            ours, theirs = getattr(bs, name), getattr(self.copy, name)
            if hasattr(ours, 'pattern'):
                ours, theirs = (ours.pattern, ours.flags), (theirs.pattern, theirs.flags)
            self.assertEqual(ours, theirs, name)

    def test_code_is_the_same(self):
        for name in SHARED_CODE:
            self.assertEqual(inspect.getsource(getattr(bs, name)), inspect.getsource(getattr(self.copy, name)), name)

    def test_a_shift_gives_the_same_document(self):
        anchor = '2026-11-19T00:04:39.980321Z'
        doc = {
            'anchor': anchor,
            'batch': {
                'batch_id': 'fleet-batch-20261119000439-9d63',
                'analysis_text': 'It was committed at 23:59:22 and restarted at 23:59:35.',
                'data': {
                    'logs': [{'_id': '1795046678914000000', '_source': {
                        '@timestamp': '2026-11-19T00:04:38.914000+00:00', 'time': 1795046678914,
                        'log': '2026-11-19 00:04:38,914 ERROR orders-api: could not enqueue'}}],
                    'change_events': [{'message': '1:M 18 Nov 2026 23:57:56.419 * Background saving started',
                                       'timestamp': '2026-11-18T23:57:56.419000+00:00'}],
                    'metrics': {'cpu': [{'time': '2026-11-18T23:58:00+00:00', 'value': 1795046678}]},
                },
            },
        }
        paths = bs.find_time_paths(doc, anchor)
        self.assertEqual(paths, self.copy.find_time_paths(doc, anchor))
        delta = -3 * 86400
        moved = self.copy.shift_times(doc, delta, paths, anchor)
        self.assertEqual(moved, bs.shift_times(doc, delta, paths, anchor))
        self.assertEqual(moved['batch']['batch_id'], 'fleet-batch-20261116000439-9d63')
        self.assertEqual(moved['batch']['analysis_text'], doc['batch']['analysis_text'])
        # A metric value that looks like epoch seconds is not under a time key: it stays.
        self.assertEqual(moved['batch']['data']['metrics']['cpu'][0]['value'], 1795046678)


if __name__ == '__main__':
    unittest.main()
