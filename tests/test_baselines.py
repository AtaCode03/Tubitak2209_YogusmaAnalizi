import unittest

from core.methods import linear_trend, threshold


class BaselineTests(unittest.TestCase):
    def test_strict_threshold(self):
        self.assertIs(threshold.predict(0.49, 0.5), True)
        self.assertIs(threshold.predict(0.5, 0.5), False)
        self.assertIsNone(threshold.predict(0, 0.5))

    def test_linear_extrapolation_and_horizon(self):
        self.assertIs(linear_trend.predict(1.0, -0.125, 5), False)
        self.assertIs(linear_trend.predict(1.0, -0.125, 10), True)
        self.assertIs(linear_trend.predict(1.0, -0.2, 5), False)
        self.assertIs(linear_trend.predict(1.0, 0.125, 15), False)

    def test_missing_features_do_not_generate_negative_decision(self):
        self.assertIsNone(threshold.predict(float('nan'), 1))
        self.assertIsNone(linear_trend.predict(0.5, None, 5))
        self.assertIsNone(linear_trend.predict(-0.5, -1, 5))
