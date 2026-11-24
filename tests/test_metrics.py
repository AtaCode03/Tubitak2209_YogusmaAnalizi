import unittest

import numpy as np

from offline.metrics import ranking, score


class MetricsTests(unittest.TestCase):
    def test_alarm_uses_period_start_and_breaks_at_missing_step(self):
        labels = np.array([0, 1, 0, 0, 1], dtype=bool)
        decisions = np.array([1, 1, 1, 0, 0], dtype=bool)
        continues = np.array([0, 1, 0, 1, 1], dtype=bool)
        result = score(labels, decisions, continues, 150)
        self.assertEqual((result['tp'], result['fp'], result['fn'], result['tn']), (1, 2, 1, 1))
        self.assertEqual(result['false_alarm_periods'], 2)
        self.assertEqual(result['false_alarms_per_24_sensor_hours'], 230.4)

    def test_undefined_f1_and_tie_break(self):
        no = np.array([False])
        self.assertIsNone(score(no, no, no, 150)['f1'])
        low = {'f1': 0.5, 'recall': 0.5, 'false_alarms_per_24_sensor_hours': 2}
        better = {**low, 'false_alarms_per_24_sensor_hours': 1}
        self.assertGreater(ranking(better, (-15,)), ranking(low, (-5,)))
        self.assertGreater(ranking(low, (-5, -100, -5, 10)), ranking(low, (-5, -100, -5, 1)))
