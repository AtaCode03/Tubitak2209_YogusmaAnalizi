import unittest

from core.windows import grid_windows


def reading(timestamp, value):
    return timestamp, (value, 90, 2, 1)


def run(readings, max_age=300):
    return list(grid_windows(iter(readings), 150, (5,), max_age))


class WindowsTest(unittest.TestCase):
    def test_future_value_cannot_change_past_features(self):
        prefix = [reading(0, 0), reading(150, 1), reading(300, 2)]
        a = run(prefix + [reading(451, 3)])
        b = run(prefix + [reading(451, 40)])
        self.assertEqual(a, b)
        self.assertEqual(a[2][1][0], 2)
        self.assertEqual(a[2][2][5][:2], (2, 1))
        self.assertAlmostEqual(a[2][2][5][4], 0.4)

    def test_stale_sample_clears_history(self):
        rows = run([reading(0, 0), reading(150, 1), reading(450, 2)], max_age=120)
        self.assertEqual(rows[2], (300, None, {}))
        self.assertEqual(rows[3][2], {})

    def test_new_block_cannot_use_previous_history(self):
        self.assertEqual(run([reading(300, 2), reading(450, 3)])[-1][2], {})
