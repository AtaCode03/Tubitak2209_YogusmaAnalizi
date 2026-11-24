import unittest

from offline.events import Event, Sample, continuity_blocks, find_events
from offline.labels import label_at


class EventLabelTests(unittest.TestCase):
    def test_start_and_confirmation_are_distinct_and_zero_ends_event(self):
        values = (1, -1, -2, -1, 0, -1, -1)
        samples = [Sample(i * 60, dpu) for i, dpu in enumerate(values)]
        self.assertEqual(find_events(samples, 120), [Event(60, 180, 180, 0)])

    def test_invalid_sample_and_large_gap_break_continuity(self):
        samples = [Sample(t, dpu) for t, dpu in ((0, -1), (60, -1), (120, None),
                                                  (180, -1), (240, -1), (420, -1), (480, -1))]
        interval, blocks = continuity_blocks(samples, 2)
        self.assertEqual(interval, 60)
        self.assertEqual([len(block) for block in blocks], [2, 2, 2])
        self.assertFalse(any(find_events(block, 120) for block in blocks))

    def test_event_at_horizon_can_be_confirmed_after_horizon(self):
        events = find_events([Sample(300, -1), Sample(360, -1), Sample(420, -1)], 120)
        self.assertEqual(events[0].confirmed, 420)
        self.assertEqual(label_at(0, 300, 120, 420, None, [300]), (1, ""))
        self.assertEqual(label_at(0, 300, 120, 419, None, [300]), (None, "incomplete_followup"))
        self.assertEqual(label_at(0, 300, 120, 420, 420, [300]), (None, "partition_boundary"))

    def test_horizons_answer_separate_questions(self):
        labels = [label_at(0, h * 60, 120, 1100, None, [420])[0] for h in (5, 10, 15)]
        self.assertEqual(labels, [0, 1, 1])

    def test_alternative_durations(self):
        samples = [Sample(0, -1), Sample(60, -1), Sample(120, 0)]
        self.assertEqual(len(find_events(samples, 0)), 1)
        self.assertEqual(find_events(samples, 300), [])
