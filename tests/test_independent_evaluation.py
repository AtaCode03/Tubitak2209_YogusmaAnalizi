import unittest

import numpy as np

from offline.bootstrap import block_counts, paired_bootstrap, time_block_analysis
from offline.evaluate_test import event_results
from offline.events import Event


class IndependentEvaluationTests(unittest.TestCase):
    def test_block_is_shared_across_series_and_excludes_partial_tail(self):
        times = np.array([1, 1, 101, 201])
        labels = np.array([1, 0, 1, 1], dtype=bool)
        good = labels.copy()
        bad = np.array([1, 1, 0, 1], dtype=bool)
        counts = block_counts(times, labels, good, bad, 0, 2, 100)
        self.assertEqual(counts.tolist(), [[[1, 0, 0], [1, 1, 0]], [[1, 0, 0], [0, 0, 1]]])

    def test_bootstrap_gates_and_paired_interval(self):
        counts = np.tile(np.array([[[1, 0, 0], [0, 0, 1]]]), (21, 1, 1))
        result = paired_bootstrap(counts, 21, 42)
        self.assertEqual(result['interval_95'], [1.0, 1.0])
        self.assertIsNone(paired_bootstrap(counts, 19, 42)['interval_95'])
        zeros = np.zeros_like(counts)
        self.assertEqual(paired_bootstrap(zeros, 21, 42)['reason'], 'too_many_undefined_repetitions')

    def test_48h_comparison_uses_same_period_as_matched_24h(self):
        times = np.arange(21) * 86400 + 60
        labels = np.ones(len(times), dtype=bool)
        result = time_block_analysis(times, labels, labels, ~labels, times, 0, 21 * 86400, 42)
        self.assertEqual(result['primary_24h']['full_blocks'], 21)
        self.assertEqual(result['sensitivity_same_period_24h']['full_blocks'], 20)
        self.assertEqual(result['sensitivity_48h']['full_blocks'], 10)
        self.assertEqual(result['conclusion'], 'desteklendi')

    def test_lead_uses_first_warning_and_checks_last_nonnegative(self):
        event = Event(600, 720, 750, 420)
        result, _, leads = event_results([event], [450, 550, 600], [True, True, True], 5, 90)
        self.assertEqual(leads, [150])
        self.assertEqual(result['timely'], 1)
        self.assertEqual(result['timely_using_last_nonnegative'], 0)
