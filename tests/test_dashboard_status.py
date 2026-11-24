import unittest

from runtime.dashboard import forecast_at, replay_label


class DashboardStatusTests(unittest.TestCase):
    def test_decision_stays_visible_between_prediction_steps(self):
        decision_time = '2025-03-13T12:10:00.000000+00:00'
        decision = {'method': 'linear', 'risk': 1}
        record = {'dpu_c': 0.5, 'measured_at': '2025-03-13T12:11:00.000000+00:00'}
        table, _, _, result_time = forecast_at(record['measured_at'], record, {decision_time: [decision]}, 120)
        self.assertEqual(table['linear'], decision)
        self.assertEqual(result_time.isoformat(timespec='microseconds'), decision_time)

    def test_new_step_has_specific_explanation_when_no_prediction_exists(self):
        record = {'dpu_c': 0.5, 'measured_at': '2025-03-13T12:12:30.000000+00:00'}
        table, status, detail, _ = forecast_at(record['measured_at'], record, {}, 120)
        self.assertFalse(table)
        self.assertEqual(status, 'Sonraki tahmin bekleniyor')
        self.assertIn('12:15:00', detail)

    def test_replay_label_does_not_show_sensor_identifier(self):
        row = {'id': 1, 'started_at': '2025-03-13T12:00:00+00:00', 'horizon_minutes': 15, 'description': 'T4.LoraA'}
        self.assertEqual(replay_label(row), 'Örnek kayıt 1 · 13.03.2025 · 15 dk tahmin')
