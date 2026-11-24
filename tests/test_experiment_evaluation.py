import unittest
from datetime import datetime, timezone

from offline.evaluate_experiments import display_metrics, score_method
from offline.evaluate_test import split_at_breaks
from offline.events import Event, Sample


def stamped(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


class ExperimentEvaluationTests(unittest.TestCase):
    def test_display_time_determines_usable_warning_and_delay(self):
        event = Event(600, 720, 750, 540)
        rows = [dict(tick=450, risk=True, first_displayed_at=stamped(570), measured_at=stamped(440)),
                dict(tick=500, risk=True, first_displayed_at=None, measured_at=stamped(490))]
        result = display_metrics(rows, [event], 5, 60)
        self.assertEqual(result['median_lead_seconds'], 30)
        self.assertEqual(result['timely_events'], 0)
        self.assertEqual(result['median_measurement_to_display_seconds'], 130)
        self.assertEqual(result['alert_rows_without_display_time'], 1)

    def test_false_alarm_duration_counts_whole_period(self):
        rows = [dict(tick=t, label=label, risk=warning, common=True, first_displayed_at=None, measured_at=stamped(t))
                for t, label, warning in ((0, 0, True), (150, 1, True), (300, 0, False), (450, 0, True))]
        result = score_method(rows, 150, [], 5, 60)
        self.assertEqual(result['records']['false_alarm_periods'], 2)
        self.assertEqual(result['records']['false_alarm_duration_seconds'], 450)

    def test_break_on_resuming_measurement_splits_block_once(self):
        samples = [Sample(t, 1) for t in (0, 30, 60, 90)]
        self.assertEqual(list(split_at_breaks([samples], [60])), [samples[:2], samples[2:]])
