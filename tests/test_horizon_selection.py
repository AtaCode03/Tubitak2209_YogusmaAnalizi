import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from offline.select_horizon import METHODS, eligible_events, select

ONSET = datetime(2025, 3, 13, 12, tzinfo=timezone.utc)


def before(minutes):
    return ONSET - timedelta(minutes=minutes)


def report(rates):
    return {str(h): {'selected': {m: {'metrics': {'false_alarms_per_24_sensor_hours': value}}
                                  for m in METHODS}} for h, value in rates.items()}


class HorizonSelectionTests(unittest.TestCase):
    def test_event_requires_same_eligible_step_across_all_horizons(self):
        rows = {5: {'A': {before(1): (1, 0, 0)}}, 10: {'A': {before(2): (1, 0, 0)}},
                15: {'A': {before(1): (1, 0, 0)}}}
        self.assertEqual(eligible_events(rows, [('A', ONSET)]), [])
        result = select(rows, [('A', ONSET)], report({5: 10, 10: 9, 15: 9}), Decimal(60))
        self.assertTrue(result['no_common_event_fallback'])
        self.assertEqual(result['selected_horizon_minutes'], 10)

    def test_first_warning_in_each_horizon_counts_toward_minimum(self):
        common = {before(2): (1, 0, 0)}
        rows = {5: {'A': common}, 10: {'A': {**common, before(8): (1, 1, 0)}},
                15: {'A': {**common, before(8): (1, 1, 0)}}}
        result = select(rows, [('A', ONSET)], report({5: 1, 10: 4, 15: 6}), Decimal(180))
        self.assertEqual(result['eligible_t4_events'], 1)
        self.assertEqual(result['selected_horizon_minutes'], 10)
        self.assertEqual(result['candidates']['10']['timely_warning_counts'], {'threshold': 1, 'linear': 1, 'random_forest': 0})
