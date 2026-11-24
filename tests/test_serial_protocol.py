import unittest
from datetime import datetime, timezone

from acquisition.protocol import MAX_LINE_BYTES, LineFramer, parse_line

FRAME = b'M1,42,1260000,10.2,88.5,9.5,184320'
NOW = datetime(2026, 11, 24, tzinfo=timezone.utc)


class SerialProtocolTests(unittest.TestCase):
    def test_fragmented_and_batched_serial_reads(self):
        receiver = LineFramer()
        self.assertEqual(list(receiver.feed(FRAME[:10])), [])
        lines = list(receiver.feed(FRAME[10:] + b'\r\n' + FRAME + b'\n'))
        self.assertEqual([parse_line(line, NOW).sequence for line in lines], [42, 42])
        packet = parse_line(lines[0], NOW)
        self.assertEqual(packet.free_heap_bytes, 184320)
        self.assertEqual(packet.measurement.timestamp, NOW)
        self.assertEqual(packet.measurement.relative_humidity_pct, 88.5)

    def test_oversized_line_is_discarded_and_reader_recovers(self):
        receiver = LineFramer()
        self.assertEqual(list(receiver.feed(b'X' * (MAX_LINE_BYTES + 1) + b'\n' + FRAME + b'\n')), [b'', FRAME])

    def test_invalid_fields_never_become_measurements(self):
        for packet in (FRAME.replace(b'M1', b'M2'), FRAME.replace(b'88.5', b'105'),
                       FRAME.replace(b'184320', b'-1'), FRAME.replace(b'9.5', b'nan')):
            with self.subTest(packet=packet), self.assertRaises(ValueError):
                parse_line(packet, NOW)
